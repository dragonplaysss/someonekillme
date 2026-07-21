import asyncio
import binascii
import os
import re
import traceback
from dataclasses import dataclass
from datetime import timedelta
from typing import Optional

import discord
import pyotp
from cryptography.fernet import Fernet, InvalidToken
from discord import app_commands
from discord.ext import commands

from cogs.mod_config import get_mod_guild_config, update_mod_guild_config
from cogs.mongo_client import get_mongo_database
from cogs.module_registry import ROBLOX_AUTH_GUILD_ID
from cogs.server_config import get_channel_id, is_owner_id
from cogs.trigger_parser import parse_shorekeeper_trigger


DEFAULT_APPROVAL_MINUTES = 10
CODE_INTERVAL_SECONDS = 30
MIN_CODE_LIFETIME_SECONDS = 5
DURATION_RE = re.compile(r"^\s*(\d+)\s*([smhd]?)\s*$", re.IGNORECASE)


def _username_key(username: str) -> str:
    return username.strip().lower()


def _utcnow():
    return discord.utils.utcnow()


def _format_seconds(total_seconds: int) -> str:
    total_seconds = max(0, int(total_seconds))
    minutes, seconds = divmod(total_seconds, 60)
    hours, minutes = divmod(minutes, 60)
    days, hours = divmod(hours, 24)
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    if seconds or not parts:
        parts.append(f"{seconds}s")
    return " ".join(parts)


def _discord_timestamp(dt=None, style: str = "F") -> str:
    value = dt or _utcnow()
    return f"<t:{int(value.timestamp())}:{style}>"


def _parse_duration(value: Optional[str]) -> timedelta:
    if not value:
        return timedelta(minutes=DEFAULT_APPROVAL_MINUTES)
    match = DURATION_RE.match(value)
    if not match:
        raise ValueError("Use a duration like `10m`, `1h`, or `30s`.")
    amount = int(match.group(1))
    unit = match.group(2).lower() or "m"
    if amount <= 0:
        raise ValueError("Duration must be greater than zero.")
    multipliers = {
        "s": timedelta(seconds=amount),
        "m": timedelta(minutes=amount),
        "h": timedelta(hours=amount),
        "d": timedelta(days=amount),
    }
    return multipliers[unit]


@dataclass
class AuthCode:
    code: str
    remaining: int


class RobloxAuthRefreshView(discord.ui.View):
    def __init__(self, cog: "RobloxAuthCog", guild_id: int, user_id: int, username_key: str, account_name: str):
        super().__init__(timeout=None)
        self.cog = cog
        self.guild_id = guild_id
        self.user_id = user_id
        self.username_key = username_key
        self.account_name = account_name

    @discord.ui.button(label="Refresh Code", style=discord.ButtonStyle.primary)
    async def refresh_code(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("This code belongs to another user.", ephemeral=True)

        approval = await self.cog.get_active_approval(self.user_id, self.username_key)
        if not approval:
            button.disabled = True
            embed = self.cog.build_dm_embed(
                account_name=self.account_name,
                code=None,
                status="APPROVAL EXPIRED",
                approval_remaining=0,
                code_remaining=0,
                requested_by=interaction.user,
            )
            embed.description = "Please request approval again."
            await interaction.response.edit_message(embed=embed, view=self)
            await self.cog.log_event(
                self.cog.get_log_guild(self.guild_id),
                "Approval Expired",
                {
                    "discord_user": interaction.user.id,
                    "roblox_username": self.account_name,
                    "expired_at": _utcnow(),
                },
            )
            return

        account = await self.cog.get_account(self.username_key)
        if not account:
            button.disabled = True
            return await interaction.response.edit_message(
                content="This Roblox account is no longer available.",
                embed=None,
                view=self,
            )

        await interaction.response.defer()
        try:
            auth_code = await self.cog.generate_code(account)
        except Exception:
            traceback.print_exc()
            await self.cog.log_event(
                self.cog.get_log_guild(self.guild_id),
                "Internal Error",
                {
                    "exception_type": "TOTPGenerationError",
                    "roblox_username": self.account_name,
                    "discord_user": interaction.user.id,
                    "operation": "Refresh authenticator code",
                },
            )
            await self.cog.log_event(
                self.cog.get_log_guild(self.guild_id),
                "Refresh Requested",
                {
                    "discord_user": interaction.user.id,
                    "roblox_username": self.account_name,
                    "result": "failed",
                },
            )
            return await interaction.followup.send("Refresh failed. Please ask staff to check logs.", ephemeral=True)

        approval_remaining = self.cog.approval_remaining_seconds(approval)
        embed = self.cog.build_dm_embed(
            account_name=account["username"],
            code=auth_code.code,
            status="ACTIVE",
            approval_remaining=approval_remaining,
            code_remaining=auth_code.remaining,
            requested_by=interaction.user,
        )
        await interaction.edit_original_response(embed=embed, view=self)
        await self.cog.log_event(
            self.cog.get_log_guild(self.guild_id),
            "Refresh Requested",
            {
                "discord_user": interaction.user.id,
                "roblox_username": account["username"],
                "result": "success",
            },
        )


class RobloxAuthCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db = get_mongo_database()
        self.accounts = self.db["roblox_accounts"]
        self.approvals = self.db["roblox_approvals"]
        self._fernet = self._load_fernet()
        self._totp_cache: dict[str, tuple[str, pyotp.TOTP]] = {}

    async def cog_load(self):
        await self.accounts.create_index("username_key", unique=True)
        await self.accounts.create_index("active")
        await self.approvals.create_index([("discord_user", 1), ("username_key", 1), ("active", 1)])
        await self.approvals.create_index("expires_at")

    def _load_fernet(self) -> Fernet:
        raw_key = os.getenv("TOTP_SECRET_KEY")
        if not raw_key:
            raise RuntimeError("TOTP_SECRET_KEY is missing. Set it in your .env file.")
        try:
            return Fernet(raw_key.encode("utf-8"))
        except (ValueError, TypeError) as exc:
            raise RuntimeError("TOTP_SECRET_KEY must be a valid Fernet key.") from exc

    def guild_allowed(self, guild: Optional[discord.Guild]) -> bool:
        return bool(guild and guild.id == ROBLOX_AUTH_GUILD_ID)

    def owner_allowed(self, user, guild: discord.Guild) -> bool:
        return is_owner_id(guild.id, user.id)

    def manager_allowed(self, member: discord.Member) -> bool:
        role_id = get_mod_guild_config(member.guild.id).get("account_manager_role")
        return bool(role_id and any(role.id == role_id for role in member.roles))

    async def ensure_owner_interaction(self, interaction: discord.Interaction) -> bool:
        if not self.guild_allowed(interaction.guild):
            await interaction.response.send_message("Unavailable in this server.", ephemeral=True)
            return False
        if not self.owner_allowed(interaction.user, interaction.guild):
            await interaction.response.send_message("No permission.", ephemeral=True)
            return False
        return True

    async def ensure_manager_interaction(self, interaction: discord.Interaction) -> bool:
        if not self.guild_allowed(interaction.guild):
            await interaction.response.send_message("Unavailable in this server.", ephemeral=True)
            return False
        if not isinstance(interaction.user, discord.Member) or not self.manager_allowed(interaction.user):
            await interaction.response.send_message("No permission.", ephemeral=True)
            return False
        return True

    def encrypt_secret(self, secret: str) -> str:
        normalized = secret.strip().replace(" ", "")
        if not normalized:
            raise ValueError("TOTP secret is required.")
        try:
            pyotp.TOTP(normalized).now()
        except (binascii.Error, ValueError):
            raise ValueError("Invalid TOTP secret.")
        return self._fernet.encrypt(normalized.encode("utf-8")).decode("utf-8")

    def decrypt_secret(self, encrypted_secret: str) -> str:
        return self._fernet.decrypt(encrypted_secret.encode("utf-8")).decode("utf-8")

    def encrypt_password(self, password: str) -> str:
        normalized = password.strip()
        if not normalized:
            raise ValueError("Password cannot be empty.")
        return self._fernet.encrypt(normalized.encode("utf-8")).decode("utf-8")

    def decrypt_password(self, encrypted_password: str) -> str:
        return self._fernet.decrypt(encrypted_password.encode("utf-8")).decode("utf-8")

    async def get_account(self, username: str):
        return await self.accounts.find_one({"username_key": _username_key(username), "active": True})

    async def get_active_approval(self, discord_user_id: int, username: str):
        now = _utcnow()
        approval = await self.approvals.find_one(
            {
                "discord_user": discord_user_id,
                "username_key": _username_key(username),
                "active": True,
                "expires_at": {"$gt": now},
            }
        )
        if approval:
            return approval

        expired = await self.approvals.update_many(
            {
                "discord_user": discord_user_id,
                "username_key": _username_key(username),
                "active": True,
                "expires_at": {"$lte": now},
            },
            {"$set": {"active": False, "expired_at": now}},
        )
        if expired.modified_count:
            await self.log_event(
                None,
                "Approval Expired",
                {
                    "discord_user": discord_user_id,
                    "roblox_username": username,
                    "expired_at": now,
                },
            )
        return None

    async def generate_code(self, account) -> AuthCode:
        encrypted = account["totp_secret"]
        username_key = account["username_key"]
        cached = self._totp_cache.get(username_key)
        if cached and cached[0] == encrypted:
            totp = cached[1]
        else:
            try:
                secret = self.decrypt_secret(encrypted)
            except InvalidToken as exc:
                raise RuntimeError("Stored authenticator secret could not be decrypted.") from exc
            totp = pyotp.TOTP(secret, interval=CODE_INTERVAL_SECONDS)
            self._totp_cache[username_key] = (encrypted, totp)

        remaining = int(totp.interval - (_utcnow().timestamp() % totp.interval))
        if remaining <= MIN_CODE_LIFETIME_SECONDS:
            await asyncio.sleep(remaining + 1)
            remaining = int(totp.interval - (_utcnow().timestamp() % totp.interval))
        return AuthCode(code=totp.now(), remaining=remaining)

    def approval_remaining_seconds(self, approval) -> int:
        expires_at = approval.get("expires_at")
        if not expires_at:
            return 0
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=_utcnow().tzinfo)
        return max(0, int((expires_at - _utcnow()).total_seconds()))

    def build_dm_embed(
        self,
        account_name: str,
        code: Optional[str],
        status: str,
        approval_remaining: int,
        code_remaining: int,
        requested_by,
        username: Optional[str] = None,
        password: Optional[str] = None,
    ) -> discord.Embed:
        status_label = "Active" if status == "ACTIVE" else "Approval Expired"
        embed = discord.Embed(title="\U0001f510 Roblox Authentication", color=0x57F287 if status == "ACTIVE" else 0xED4245)
        embed.add_field(name="\U0001f3ae Roblox Account", value=account_name, inline=False)
        if username:
            embed.add_field(name="\U0001f464 Username", value=username, inline=False)
        if password:
            embed.add_field(name="\U0001f511 Password", value=f"||{password}||", inline=False)
        if code is not None:
            embed.add_field(name="\U0001f522 Authenticator Code", value=f"`{code}`", inline=False)
        embed.add_field(name="Status", value=status_label, inline=False)
        embed.add_field(name="\u23f3 Approval Remaining", value=_format_seconds(approval_remaining), inline=True)
        embed.add_field(name="\u231b Code Remaining", value=f"{code_remaining} seconds", inline=True)
        embed.add_field(name="Requested By", value=requested_by.mention, inline=False)
        return embed

    def get_log_guild(self, guild_id: int):
        return self.bot.get_guild(guild_id) or self.bot.get_guild(ROBLOX_AUTH_GUILD_ID)

    def _parse_log_detail(self, detail):
        if isinstance(detail, dict):
            return {str(key): value for key, value in detail.items() if value is not None}

        parsed = {}
        for item in str(detail).split():
            if "=" not in item:
                continue
            key, value = item.split("=", 1)
            parsed[key] = value
        return parsed

    def _format_log_value(self, key: str, value):
        if value is None:
            return "Unknown"
        if key.endswith("_user") or key in {"discord_user", "approved_by", "revoked_by", "rejected_by", "updated_by", "by", "added_by", "edited_by", "removed_by"}:
            return f"<@{value}>"
        if key in {"channel", "channel_id"}:
            return f"<#{value}>"
        if key in {"guild", "guild_id"}:
            return str(value)
        if key in {"expires_at", "expired_at"}:
            if hasattr(value, "timestamp"):
                return f"{_discord_timestamp(value, 'R')} ({_discord_timestamp(value, 'F')})"
            return str(value)
        if key in {"timestamp", "created_at"} and hasattr(value, "timestamp"):
            return _discord_timestamp(value, "F")
        return str(value)

    def _add_log_field(self, embed: discord.Embed, name: str, value, inline: bool = True):
        embed.add_field(name=name, value=str(value)[:1024] or "Unknown", inline=inline)

    def _build_log_embed(self, action: str, detail):
        data = self._parse_log_detail(detail)
        colors = {
            "Approval Granted": 0x57F287,
            "Approval Revoked": 0xED4245,
            "Approval Rejected": 0xF97316,
            "Unauthorized Attempt": 0x992D22,
            "DM Failed": 0xFEE75C,
            "Refresh Requested": 0x5865F2,
            "Approval Expired": 0x747F8D,
            "Account Added": 0x3498DB,
            "Account Edited": 0x3498DB,
            "Account Removed": 0xED4245,
            "Auth Requested": 0x5865F2,
            "Account Manager Role Updated": 0x3498DB,
            "Internal Error": 0xFEE75C,
        }
        icon = "\u26a0" if action == "Internal Error" else "\U0001f510"
        embed = discord.Embed(
            title=f"{icon} Roblox Auth \u2022 {action}",
            color=colors.get(action, 0x5865F2),
            timestamp=_utcnow(),
        )

        if action == "Account Manager Role Updated":
            self._add_log_field(embed, "\U0001f6e1 Role", self._format_log_value("role", data.get("role")), True)
            self._add_log_field(embed, "\U0001f6e1 Updated By", self._format_log_value("updated_by", data.get("updated_by")), True)
        elif action == "Account Added":
            self._add_log_field(embed, "\U0001f3ae Username", data.get("roblox_username") or data.get("username"), True)
            self._add_log_field(embed, "\U0001f464 Display Name", data.get("display_name", "Not provided"), True)
            self._add_log_field(embed, "\U0001f4e7 Linked Gmail", data.get("linked_gmail") or data.get("gmail") or "Not provided", False)
            self._add_log_field(embed, "\U0001f6e1 Added By", self._format_log_value("added_by", data.get("added_by") or data.get("by")), True)
        elif action == "Account Edited":
            self._add_log_field(embed, "\U0001f3ae Username", data.get("roblox_username") or data.get("username"), True)
            self._add_log_field(embed, "\U0001f6e1 Edited By", self._format_log_value("edited_by", data.get("edited_by") or data.get("by")), True)
        elif action == "Account Removed":
            self._add_log_field(embed, "\U0001f3ae Username", data.get("roblox_username") or data.get("username"), True)
            self._add_log_field(embed, "\U0001f6e1 Removed By", self._format_log_value("removed_by", data.get("removed_by") or data.get("by")), True)
        elif action == "Approval Granted":
            self._add_log_field(embed, "\U0001f464 User", self._format_log_value("discord_user", data.get("discord_user")), True)
            self._add_log_field(embed, "\U0001f3ae Roblox Account", data.get("roblox_username"), True)
            self._add_log_field(embed, "\U0001f6e1 Approved By", self._format_log_value("approved_by", data.get("approved_by")), True)
            if data.get("duration"):
                self._add_log_field(embed, "\u23f3 Duration", data.get("duration"), True)
            if data.get("expires_at"):
                self._add_log_field(embed, "\U0001f552 Expiration Time", self._format_log_value("expires_at", data.get("expires_at")), False)
        elif action == "Approval Revoked":
            self._add_log_field(embed, "\U0001f464 User", self._format_log_value("discord_user", data.get("discord_user")), True)
            self._add_log_field(embed, "\U0001f3ae Roblox Account", data.get("roblox_username"), True)
            self._add_log_field(embed, "\U0001f6e1 Revoked By", self._format_log_value("revoked_by", data.get("revoked_by")), True)
        elif action == "Approval Rejected":
            self._add_log_field(embed, "\U0001f464 User", self._format_log_value("discord_user", data.get("discord_user")), True)
            self._add_log_field(embed, "\U0001f3ae Roblox Account", data.get("roblox_username"), True)
            self._add_log_field(embed, "\U0001f6e1 Rejected By", self._format_log_value("rejected_by", data.get("rejected_by")), True)
        elif action == "Approval Expired":
            self._add_log_field(embed, "\U0001f464 User", self._format_log_value("discord_user", data.get("discord_user", "Unknown")), True)
            self._add_log_field(embed, "\U0001f3ae Roblox Account", data.get("roblox_username", "Unknown"), True)
            self._add_log_field(embed, "\U0001f552 Expired At", self._format_log_value("expired_at", data.get("expired_at") or _utcnow()), False)
            if data.get("expired_count"):
                self._add_log_field(embed, "\U0001f4ca Expired Count", data.get("expired_count"), True)
        elif action == "Auth Requested":
            result = str(data.get("result", "Unknown")).replace("_", " ").title()
            self._add_log_field(embed, "\U0001f464 User", self._format_log_value("discord_user", data.get("discord_user")), True)
            self._add_log_field(embed, "\U0001f3ae Roblox Account", data.get("roblox_username"), True)
            self._add_log_field(embed, "\U0001f4cc Result", result, True)
            if data.get("password_included") is not None:
                self._add_log_field(embed, "\U0001f511 Password Included", data.get("password_included"), True)
        elif action == "Refresh Requested":
            result = str(data.get("result", "Unknown")).replace("_", " ").title()
            self._add_log_field(embed, "\U0001f464 User", self._format_log_value("discord_user", data.get("discord_user")), True)
            self._add_log_field(embed, "\U0001f3ae Roblox Account", data.get("roblox_username"), True)
            self._add_log_field(embed, "\U0001f4cc Result", result, True)
        elif action == "DM Failed":
            self._add_log_field(embed, "\U0001f464 User", self._format_log_value("discord_user", data.get("discord_user")), True)
            self._add_log_field(embed, "\U0001f3ae Roblox Account", data.get("roblox_username"), True)
            self._add_log_field(embed, "\U0001f4cc Reason", data.get("reason", "User cannot receive direct messages."), False)
        elif action == "Unauthorized Attempt":
            self._add_log_field(embed, "\U0001f464 User", self._format_log_value("discord_user", data.get("discord_user")), True)
            self._add_log_field(embed, "\U0001f3ae Roblox Account", data.get("roblox_username"), True)
            self._add_log_field(embed, "\U0001f4cd Channel", self._format_log_value("channel_id", data.get("channel_id")), True)
            self._add_log_field(embed, "\U0001f3e0 Guild", self._format_log_value("guild_id", data.get("guild_id")), True)
        elif action == "Internal Error":
            self._add_log_field(embed, "Exception Type", data.get("exception_type", "Unknown"), True)
            self._add_log_field(embed, "\U0001f3ae Roblox Account", data.get("roblox_username", "Unknown"), True)
            self._add_log_field(embed, "\U0001f464 Discord User", self._format_log_value("discord_user", data.get("discord_user")), True)
            self._add_log_field(embed, "Operation", data.get("operation", "Unknown"), False)
        else:
            for key, value in data.items():
                self._add_log_field(embed, key.replace("_", " ").title(), self._format_log_value(key, value), True)

        self._add_log_field(embed, "\U0001f552 Timestamp", _discord_timestamp(style="R"), False)
        embed.set_footer(text="Shorekeeper Roblox Authentication")
        return embed

    async def log_event(self, guild: Optional[discord.Guild], action: str, detail: str):
        target_guild = guild or self.bot.get_guild(ROBLOX_AUTH_GUILD_ID)
        if not target_guild:
            print(f"[ROBLOX AUTH LOG] {action}: {detail}")
            return
        channel_id = get_channel_id(target_guild.id, "mod_logs") or get_channel_id(target_guild.id, "logging")
        channel = target_guild.get_channel(channel_id) if channel_id else None
        if not channel:
            print(f"[ROBLOX AUTH LOG] {action}: {detail}")
            return
        embed = self._build_log_embed(action, detail)
        await channel.send(embed=embed)

    @app_commands.command(name="rbxmanagerrole", description="Set the Roblox auth account manager role.")
    async def rbxmanagerrole(self, interaction: discord.Interaction, role: discord.Role):
        if not await self.ensure_owner_interaction(interaction):
            return

        update_mod_guild_config(interaction.guild.id, lambda config: config.update({"account_manager_role": role.id}))
        await interaction.response.send_message(f"Account manager role set to {role.mention}.", ephemeral=True)
        await self.log_event(interaction.guild, "Account Manager Role Updated", f"role={role.id} updated_by={interaction.user.id}")

    @app_commands.command(name="rbxadd", description="Add a Roblox authenticator account.")
    async def rbxadd(
        self,
        interaction: discord.Interaction,
        username: str,
        display_name: str,
        linked_gmail: str,
        totp_secret: str,
        password: Optional[str] = None,
    ):
        if not await self.ensure_owner_interaction(interaction):
            return

        await interaction.response.defer(ephemeral=True, thinking=True)
        username = username.strip()
        try:
            encrypted_secret = self.encrypt_secret(totp_secret)
            encrypted_password = self.encrypt_password(password) if password is not None else None
        except ValueError as exc:
            return await interaction.followup.send(str(exc), ephemeral=True)
        now = _utcnow()
        account_updates = {
            "username": username,
            "username_key": _username_key(username),
            "display_name": display_name.strip(),
            "gmail": linked_gmail.strip() or None,
            "totp_secret": encrypted_secret,
            "active": True,
            "updated_by": interaction.user.id,
            "updated_at": now,
        }
        if encrypted_password is not None:
            account_updates["password"] = encrypted_password
        await self.accounts.update_one(
            {"username_key": _username_key(username)},
            {
                "$set": account_updates,
                "$setOnInsert": {
                    "created_by": interaction.user.id,
                    "created_at": now,
                },
            },
            upsert=True,
        )
        self._totp_cache.pop(_username_key(username), None)
        await interaction.followup.send(f"`{username}` saved.", ephemeral=True)
        await self.log_event(interaction.guild, "Account Added", f"roblox_username={username} by={interaction.user.id}")

    @app_commands.command(name="rbxedit", description="Edit a Roblox authenticator account.")
    async def rbxedit(
        self,
        interaction: discord.Interaction,
        username: str,
        display_name: Optional[str] = None,
        linked_gmail: Optional[str] = None,
        totp_secret: Optional[str] = None,
        active: Optional[bool] = None,
        password: Optional[str] = None,
        clear_password: Optional[bool] = False,
    ):
        if not await self.ensure_owner_interaction(interaction):
            return

        await interaction.response.defer(ephemeral=True, thinking=True)
        account = await self.accounts.find_one({"username_key": _username_key(username)})
        if not account:
            return await interaction.followup.send("Account not found.", ephemeral=True)

        updates = {"updated_by": interaction.user.id, "updated_at": _utcnow()}
        if display_name is not None:
            updates["display_name"] = display_name.strip()
        if linked_gmail is not None:
            updates["gmail"] = linked_gmail.strip() or None
        if active is not None:
            updates["active"] = active
        if totp_secret is not None:
            try:
                updates["totp_secret"] = self.encrypt_secret(totp_secret)
            except ValueError as exc:
                return await interaction.followup.send(str(exc), ephemeral=True)
            self._totp_cache.pop(_username_key(username), None)
        if password is not None:
            try:
                updates["password"] = self.encrypt_password(password)
            except ValueError as exc:
                return await interaction.followup.send(str(exc), ephemeral=True)

        update_doc = {"$set": updates}
        if clear_password:
            updates.pop("password", None)
            update_doc["$unset"] = {"password": ""}

        await self.accounts.update_one({"_id": account["_id"]}, update_doc)
        await interaction.followup.send(f"`{account['username']}` updated.", ephemeral=True)
        await self.log_event(interaction.guild, "Account Edited", f"roblox_username={account['username']} by={interaction.user.id}")

    @app_commands.command(name="rbxremove", description="Delete a Roblox authenticator account.")
    async def rbxremove(self, interaction: discord.Interaction, username: str):
        if not await self.ensure_owner_interaction(interaction):
            return

        account = await self.accounts.find_one({"username_key": _username_key(username)})
        if not account:
            return await interaction.response.send_message("Account not found.", ephemeral=True)

        await self.accounts.delete_one({"_id": account["_id"]})
        await self.approvals.update_many(
            {"username_key": account["username_key"], "active": True},
            {"$set": {"active": False, "revoked_at": _utcnow(), "revoked_reason": "account_removed"}},
        )
        self._totp_cache.pop(account["username_key"], None)
        await interaction.response.send_message(f"`{account['username']}` removed.", ephemeral=True)
        await self.log_event(interaction.guild, "Account Removed", f"roblox_username={account['username']} by={interaction.user.id}")

    @app_commands.command(name="rbxlist", description="List Roblox authenticator accounts.")
    async def rbxlist(self, interaction: discord.Interaction):
        if not await self.ensure_owner_interaction(interaction):
            return

        accounts = await self.accounts.find({}).sort("username_key", 1).to_list(100)
        if not accounts:
            return await interaction.response.send_message("No Roblox accounts configured.", ephemeral=True)

        lines = []
        for account in accounts:
            approval = await self.approvals.find_one(
                {"username_key": account["username_key"], "active": True, "expires_at": {"$gt": _utcnow()}}
            )
            assigned = f"<@{approval['discord_user']}>" if approval else "None"
            status = "Active" if account.get("active", True) else "Inactive"
            lines.append(f"`{account['username']}` | assigned={assigned} | status={status}")

        embed = discord.Embed(title="Roblox Auth Accounts", description="\n".join(lines)[:4000], color=0x5865F2)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="rbxinfo", description="Show Roblox authenticator account information.")
    async def rbxinfo(self, interaction: discord.Interaction, username: str):
        if not await self.ensure_owner_interaction(interaction):
            return

        account = await self.accounts.find_one({"username_key": _username_key(username)})
        if not account:
            return await interaction.response.send_message("Account not found.", ephemeral=True)

        embed = discord.Embed(title="Roblox Account Info", color=0x5865F2)
        embed.add_field(name="Username", value=account.get("username", "Unknown"), inline=True)
        embed.add_field(name="Display Name", value=account.get("display_name") or "Not set", inline=True)
        embed.add_field(name="Linked Gmail", value=account.get("gmail") or "Not set", inline=False)
        embed.add_field(name="Status", value="Active" if account.get("active", True) else "Inactive", inline=True)
        embed.add_field(name="Created By", value=f"<@{account.get('created_by')}>", inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="approveauth", description="Approve a user to request a Roblox authenticator code.")
    async def approveauth(
        self,
        interaction: discord.Interaction,
        discord_user: discord.Member,
        roblox_username: str,
        duration: Optional[str] = None,
    ):
        if not await self.ensure_manager_interaction(interaction):
            return

        account = await self.get_account(roblox_username)
        if not account:
            return await interaction.response.send_message("Account not found or inactive.", ephemeral=True)

        try:
            approval_duration = _parse_duration(duration)
        except ValueError as exc:
            return await interaction.response.send_message(str(exc), ephemeral=True)

        now = _utcnow()
        expires_at = now + approval_duration
        await self.approvals.update_many(
            {"username_key": account["username_key"], "active": True},
            {"$set": {"active": False, "replaced_at": now}},
        )
        await self.approvals.insert_one(
            {
                "discord_user": discord_user.id,
                "roblox_username": account["username"],
                "username_key": account["username_key"],
                "approved_by": interaction.user.id,
                "approved_at": now,
                "expires_at": expires_at,
                "active": True,
            }
        )
        await interaction.response.send_message(
            f"{discord_user.mention} approved for `{account['username']}` for {_format_seconds(int(approval_duration.total_seconds()))}.",
            ephemeral=True,
        )
        await self.log_event(
            interaction.guild,
            "Approval Granted",
            f"discord_user={discord_user.id} roblox_username={account['username']} approved_by={interaction.user.id}",
        )

    @app_commands.command(name="rejectauth", description="Reject active auth approvals for a user and account.")
    async def rejectauth(self, interaction: discord.Interaction, discord_user: discord.Member, roblox_username: str):
        if not await self.ensure_manager_interaction(interaction):
            return

        result = await self.approvals.update_many(
            {"discord_user": discord_user.id, "username_key": _username_key(roblox_username), "active": True},
            {"$set": {"active": False, "rejected_by": interaction.user.id, "rejected_at": _utcnow()}},
        )
        await interaction.response.send_message(f"Rejected `{result.modified_count}` approval(s).", ephemeral=True)
        await self.log_event(
            interaction.guild,
            "Approval Rejected",
            f"discord_user={discord_user.id} roblox_username={roblox_username} rejected_by={interaction.user.id}",
        )

    @app_commands.command(name="revokeauth", description="Immediately revoke active auth approval.")
    async def revokeauth(self, interaction: discord.Interaction, discord_user: discord.Member, roblox_username: str):
        if not await self.ensure_manager_interaction(interaction):
            return

        result = await self.approvals.update_many(
            {"discord_user": discord_user.id, "username_key": _username_key(roblox_username), "active": True},
            {"$set": {"active": False, "revoked_by": interaction.user.id, "revoked_at": _utcnow()}},
        )
        await interaction.response.send_message(f"Revoked `{result.modified_count}` approval(s).", ephemeral=True)
        await self.log_event(
            interaction.guild,
            "Approval Revoked",
            f"discord_user={discord_user.id} roblox_username={roblox_username} revoked_by={interaction.user.id}",
        )

    @app_commands.command(name="activeapprovals", description="List active Roblox auth approvals.")
    async def activeapprovals(self, interaction: discord.Interaction):
        if not await self.ensure_manager_interaction(interaction):
            return

        now = _utcnow()
        expired = await self.approvals.update_many(
            {"active": True, "expires_at": {"$lte": now}},
            {"$set": {"active": False, "expired_at": now}},
        )
        if expired.modified_count:
            await self.log_event(interaction.guild, "Approval Expired", f"expired_count={expired.modified_count}")
        approvals = await self.approvals.find({"active": True, "expires_at": {"$gt": now}}).sort("expires_at", 1).to_list(100)
        if not approvals:
            return await interaction.response.send_message("No active approvals.", ephemeral=True)

        lines = []
        for approval in approvals:
            remaining = self.approval_remaining_seconds(approval)
            lines.append(
                f"<@{approval['discord_user']}> | `{approval['roblox_username']}` | remaining={_format_seconds(remaining)}"
            )
        embed = discord.Embed(title="Active Roblox Auth Approvals", description="\n".join(lines)[:4000], color=0x5865F2)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if not self.guild_allowed(message.guild):
            return

        trigger = parse_shorekeeper_trigger(self.bot, message)
        if not trigger or trigger["keyword"] != "robloxauth":
            return

        username = " ".join(trigger["args"]).strip()
        if not username:
            return await message.channel.send("Use `@Shorekeeper robloxauth RobloxUsername`.", delete_after=8)

        account = await self.get_account(username)
        approval = await self.get_active_approval(message.author.id, username)
        if not approval or not account:
            await self.log_event(
                message.guild,
                "Unauthorized Attempt",
                f"discord_user={message.author.id} roblox_username={username}",
            )
            return

        password_included = False
        try:
            auth_code = await self.generate_code(account)
            approval_remaining = self.approval_remaining_seconds(approval)
            password = None
            encrypted_password = account.get("password")
            if encrypted_password:
                try:
                    password = self.decrypt_password(encrypted_password)
                except InvalidToken:
                    traceback.print_exc()
                    await self.log_event(
                        message.guild,
                        "Internal Error",
                        {
                            "exception_type": "InvalidToken",
                            "roblox_username": account["username"],
                            "discord_user": message.author.id,
                            "operation": "Decrypt stored password",
                        },
                    )
            password_included = password is not None
            embed = self.build_dm_embed(
                account_name=account.get("display_name") or account["username"],
                code=auth_code.code,
                status="ACTIVE",
                approval_remaining=approval_remaining,
                code_remaining=auth_code.remaining,
                requested_by=message.author,
                username=account["username"],
                password=password,
            )
            view = RobloxAuthRefreshView(self, message.guild.id, message.author.id, account["username_key"], account["username"])
            await message.author.send(embed=embed, view=view)
            await message.add_reaction("\u2705")
            await self.log_event(
                message.guild,
                "Auth Requested",
                {
                    "discord_user": message.author.id,
                    "roblox_username": account["username"],
                    "result": "dm_sent",
                    "password_included": "Yes" if password_included else "No",
                },
            )
        except discord.Forbidden:
            await self.log_event(
                message.guild,
                "DM Failed",
                f"discord_user={message.author.id} roblox_username={username}",
            )
            await message.channel.send("I could not DM you. Enable DMs and try again.", delete_after=10)
        except Exception as exc:
            await self.log_event(
                message.guild,
                "Auth Requested",
                {
                    "discord_user": message.author.id,
                    "roblox_username": username,
                    "result": "failed",
                    "error": type(exc).__name__,
                    "password_included": "Yes" if password_included else "No",
                },
            )
            await message.channel.send("Authenticator request failed. Ask staff to check logs.", delete_after=10)


async def setup(bot):
    await bot.add_cog(RobloxAuthCog(bot))
