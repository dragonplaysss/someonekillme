import datetime
import random
import re

import discord
from discord.ext import commands

from cogs.core.responses import response_engine
from cogs.mongo_client import get_mongo_database
from cogs.module_registry import MODULES, get_module_state, mention_command_list, module_names
from cogs.server_config import get_guild_config, immunity_reason, is_admin, is_owner_id, is_panel_owner, update_guild_config
from cogs.trigger_parser import parse_shorekeeper_trigger


class MiscToolsCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db = get_mongo_database()
        self.warns = self.db["warns"]
        self.bark_locks = self.db["bark_locks"]
        self.uwu_locks = self.db["uwu_locks"]
        self.afk = self.db["afk"]
        self.webhook_cache = {}
        self.afk_notice_delete_after = 2

    async def cog_load(self):
        await self.bark_locks.create_index([("guild_id", 1), ("user_id", 1)], unique=True)
        await self.uwu_locks.create_index([("guild_id", 1), ("user_id", 1)], unique=True)
        await self.afk.create_index([("guild_id", 1), ("user_id", 1)], unique=True)

    def _parse_id(self, raw: str):
        digits = "".join(ch for ch in raw if ch.isdigit())
        return int(digits) if digits else None

    def _can_owner_admin(self, message: discord.Message):
        return is_admin(message.author) or is_owner_id(message.guild.id, message.author.id)

    def _can_owner_only(self, message: discord.Message):
        return is_owner_id(message.guild.id, message.author.id)

    def _module_loaded(self, module):
        meta = MODULES.get(module, {})
        extensions = meta.get("extensions") or [meta.get("extension")]
        return all(ext in self.bot.extensions for ext in extensions if ext)

    def _active_module_names(self, guild_config):
        return [
            module
            for module in module_names()
            if get_module_state(guild_config, module) != "disabled"
            and self._module_loaded(module)
        ]

    def _format_role(self, guild: discord.Guild, role_id):
        role = guild.get_role(role_id) if role_id else None
        return role.mention if role else str(role_id) if role_id else "Not set"

    def _format_channel(self, guild: discord.Guild, channel_id):
        channel = guild.get_channel(channel_id) if channel_id else None
        return channel.mention if channel else str(channel_id) if channel_id else "Not set"

    def _uwuify(self, text: str):
        if not text:
            return "uwu"
        converted = re.sub(r"[rl]", "w", text)
        converted = re.sub(r"[RL]", "W", converted)
        converted = re.sub(r"n([aeiouAEIOU])", r"ny\1", converted)
        suffix = random.choice([" uwu", " owo", " >w<"])
        return (converted.strip() + suffix)[:1800]

    async def _get_relay_webhook(self, channel: discord.TextChannel):
        # Don't auto-create webhooks - only return existing ones
        cached_id = self.webhook_cache.get(channel.id)
        if cached_id:
            try:
                webhooks = await channel.webhooks()
                for hook in webhooks:
                    if hook.id == cached_id:
                        return hook
                # Cached webhook not found, remove from cache
                self.webhook_cache.pop(channel.id, None)
            except Exception:
                # Failed to fetch webhooks, remove from cache
                self.webhook_cache.pop(channel.id, None)
                return None

        # No cached webhook, look for existing "Shorekeeper Relay" webhook
        try:
            webhooks = await channel.webhooks()
            for hook in webhooks:
                if hook.name == "Shorekeeper Relay":
                    self.webhook_cache[channel.id] = hook.id
                    return hook
        except Exception:
            pass

        # No existing webhook found, return None (don't auto-create)
        return None

    async def _send_embed_via_webhook(self, channel: discord.TextChannel, embed: discord.Embed) -> bool:
        """Try to send embed via webhook, return True if successful"""
        webhook = await self._get_relay_webhook(channel)
        if not webhook:
            return False

        try:
            await webhook.send(
                embed=embed,
                username="Shorekeeper",
                avatar_url=self.bot.user.display_avatar.url if self.bot.user else None
            )
            return True
        except Exception:
            return False

    async def _relay_as_user(self, message: discord.Message, content: str):
        if not isinstance(message.channel, discord.TextChannel):
            return False
        hook = await self._get_relay_webhook(message.channel)
        if not hook:
            return False
        try:
            await hook.send(
                content=content[:1900],
                username=message.author.display_name,
                avatar_url=message.author.display_avatar.url,
                allowed_mentions=discord.AllowedMentions.none(),
            )
            return True
        except Exception:
            return False

    async def _send_security_log(self, guild, action, moderator, target, reason):
        channel_id = get_guild_config(guild.id).get("channels", {}).get("mod_logs") or get_guild_config(guild.id).get("channels", {}).get("logging")
        channel = guild.get_channel(channel_id) if channel_id else None
        if not channel:
            return
        embed = response_engine.build(
            title=f"Security: {action}",
            description="",
            color=0xED4245
        )
        embed.add_field(name="Target", value=f"{target.mention} ({target.id})", inline=False)
        embed.add_field(name="Moderator", value=moderator.mention, inline=True)
        embed.add_field(name="Reason", value=reason, inline=False)
        sent = await self._send_embed_via_webhook(channel, embed)
        if not sent:
            await channel.send(embed=embed)

    async def _enforce_fun_locks(self, message: discord.Message):
        if message.author.bot:
            return False
        if immunity_reason(message.author, "barklock") or immunity_reason(message.author, "uwulock"):
            await self.bark_locks.delete_one({"guild_id": message.guild.id, "user_id": message.author.id})
            await self.uwu_locks.delete_one({"guild_id": message.guild.id, "user_id": message.author.id})
            return False
        if await self.bark_locks.find_one({"guild_id": message.guild.id, "user_id": message.author.id}):
            try:
                await message.delete()
            except Exception:
                return False
            await self._relay_as_user(message, random.choice(["bark", "woof"]))
            return True
        if await self.uwu_locks.find_one({"guild_id": message.guild.id, "user_id": message.author.id}):
            try:
                await message.delete()
            except Exception:
                return False
            await self._relay_as_user(message, self._uwuify(message.content))
            return True
        return False

    async def _set_afk_nick(self, member: discord.Member):
        if not self._can_edit_nick(member):
            return None, False

        original_nick = member.nick
        display_name = member.display_name
        if display_name.upper().startswith("[AFK]"):
            return original_nick, True

        try:
            new_nick = f"[AFK] {display_name}"[:32]
            await member.edit(nick=new_nick, reason="AFK enabled")
            return original_nick, True
        except Exception:
            return original_nick, False

    async def _restore_afk_nick(self, member: discord.Member, original_nick):
        if not self._can_edit_nick(member):
            return False
        if not member.display_name.upper().startswith("[AFK]"):
            return True
        try:
            await member.edit(nick=original_nick, reason="AFK disabled")
            return True
        except Exception:
            return False

    def _reply_author_id(self, message: discord.Message):
        reference = message.reference
        if not reference:
            return None
        resolved = getattr(reference, "resolved", None)
        if isinstance(resolved, discord.Message):
            return resolved.author.id
        return None

    async def _notify_afk_target(self, message: discord.Message, user_id: int, afk_status):
        member = message.guild.get_member(user_id)
        label = member.mention if member else f"<@{user_id}>"
        reason = afk_status.get("reason") or "AFK"
        since = afk_status.get("since")
        if since and since.tzinfo is None:
            since = since.replace(tzinfo=datetime.timezone.utc)
        suffix = f" since {discord.utils.format_dt(since, 'R')}" if since else ""

        try:
            await message.delete()
        except Exception:
            pass

        embed = response_engine.info(
            title="AFK Status",
            description=f"{label} is AFK{suffix}: {reason}"
        )
        await message.channel.send(
            embed=embed,
            allowed_mentions=discord.AllowedMentions.none(),
            delete_after=self.afk_notice_delete_after,
        )

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        if await self._enforce_fun_locks(message):
            return

        trigger = parse_shorekeeper_trigger(self.bot, message)
        if trigger and trigger["keyword"] == "afk":
            reason = trigger["extra"] or " ".join(trigger["args"]) or "AFK"
            original_nick, nick_changed = await self._set_afk_nick(message.author)
            await self.afk.update_one(
                {"guild_id": message.guild.id, "user_id": message.author.id},
                {
                    "$set": {
                        "reason": reason[:500],
                        "since": discord.utils.utcnow(),
                        "original_nick": original_nick,
                        "nick_changed": nick_changed,
                    }
                },
                upsert=True,
            )
            suffix = "" if nick_changed else " I could not change your nickname."
            embed = response_engine.info(
                title="AFK Status",
                description=f"{message.author.mention} is now AFK: {reason[:500]}{suffix}"
            )
            await message.channel.send(
                embed=embed,
                allowed_mentions=discord.AllowedMentions.none(),
                delete_after=self.afk_notice_delete_after,
            )
            return

        existing_afk = await self.afk.find_one({"guild_id": message.guild.id, "user_id": message.author.id})
        if existing_afk:
            await self._restore_afk_nick(message.author, existing_afk.get("original_nick"))
            await self.afk.delete_one({"guild_id": message.guild.id, "user_id": message.author.id})
            embed = response_engine.success(
                title="Welcome Back",
                description=f"Welcome back {message.author.mention}. I removed your AFK."
            )
            await message.channel.send(
                embed=embed,
                allowed_mentions=discord.AllowedMentions.none(),
                delete_after=self.afk_notice_delete_after,
            )
            return

        mentioned_ids = {
            member.id
            for member in message.mentions
            if member.id not in {message.author.id, self.bot.user.id}
        }
        reply_author_id = self._reply_author_id(message)
        if reply_author_id and reply_author_id not in {message.author.id, self.bot.user.id}:
            mentioned_ids.add(reply_author_id)

        for user_id in mentioned_ids:
            afk_status = await self.afk.find_one({"guild_id": message.guild.id, "user_id": user_id})
            if not afk_status:
                continue
            await self._notify_afk_target(message, user_id, afk_status)
            return

        if not trigger:
            return

        keyword = trigger["keyword"]
        target = trigger["target"] or message.author

        if keyword == "ping":
            embed = response_engine.info(
                title="Pong!",
                description=f"Latency: `{round(self.bot.latency * 1000)}`ms"
            )
            await message.channel.send(embed=embed)
            return

        if keyword == "avatar":
            embed = response_engine.build(title=f"{target} Avatar", description="", color=0x95A5A6)
            embed.set_image(url=target.display_avatar.url)
            await message.channel.send(embed=embed)
            return

        if keyword == "serverinfo":
            guild = message.guild
            embed = response_engine.build(
                title=f"{guild.name} Server Info",
                description="",
                color=0x5865F2
            )
            embed.add_field(name="Members", value=str(guild.member_count), inline=True)
            embed.add_field(name="Channels", value=str(len(guild.channels)), inline=True)
            embed.add_field(name="Roles", value=str(len(guild.roles)), inline=True)
            embed.add_field(name="Owner", value=guild.owner.mention if guild.owner else "Unknown", inline=False)
            if guild.icon:
                embed.set_thumbnail(url=guild.icon.url)
            await message.channel.send(embed=embed)
            return

        if keyword == "userinfo":
            member = target if isinstance(target, discord.Member) else message.guild.get_member(target.id)
            if not member:
                embed = response_engine.failure(
                    title="Member Not Found",
                    description="The specified member could not be found."
                )
                await message.channel.send(embed=embed)
                return
            embed = response_engine.build(
                title=f"{member} User Info",
                description="",
                color=0x2ECC71
            )
            embed.add_field(name="ID", value=str(member.id), inline=True)
            embed.add_field(name="Joined", value=discord.utils.format_dt(member.joined_at, "R"), inline=True)
            embed.add_field(name="Created", value=discord.utils.format_dt(member.created_at, "R"), inline=True)
            embed.add_field(name="Top Role", value=member.top_role.mention, inline=False)
            embed.set_thumbnail(url=member.display_avatar.url)
            await message.channel.send(embed=embed)
            return

        if keyword == "warns":
            count = await self.warns.count_documents({"guild_id": message.guild.id, "user_id": target.id})
            embed = response_engine.info(
                title="Warn Count",
                description=f"{target.mention} has `{count}` warn(s)."
            )
            await message.channel.send(embed=embed)
            return

        if keyword == "whoami":
            cfg = get_guild_config(message.guild.id)
            owner_ids = set(cfg.get("owner_ids", []))
            admin_ids = set(cfg.get("admin_ids", []))
            admin_roles = set(cfg.get("admin_roles", []))
            mod_roles = set(cfg.get("mod_roles", []))
            my_role_ids = {role.id for role in message.author.roles}
            embed = response_engine.build(
                title="Permission Check",
                description="",
                color=0x1ABC9C
            )
            embed.add_field(name="User", value=f"{message.author.mention} (`{message.author.id}`)", inline=False)
            embed.add_field(name="is_panel_owner", value=str(is_panel_owner(message.author.id)), inline=True)
            embed.add_field(name="is_owner_id", value=str(is_owner_id(message.guild.id, message.author.id)), inline=True)
            embed.add_field(name="is_admin", value=str(is_admin(message.author)), inline=True)
            embed.add_field(
                name="is_mod",
                value=str(message.author.guild_permissions.administrator or bool(my_role_ids & mod_roles or my_role_ids & admin_roles)),
                inline=True
            )
            embed.add_field(
                name="Matched Config Roles",
                value=(
                    f"admin_roles matched: `{len(my_role_ids & admin_roles)}`\n"
                    f"mod_roles matched: `{len(my_role_ids & mod_roles)}`\n"
                    f"in admin_ids: `{message.author.id in admin_ids}`\n"
                    f"in owner_ids: `{message.author.id in owner_ids}`"
                ),
                inline=False,
            )
            await message.channel.send(embed=embed)
            return

        if keyword in {"config", "showconfig", "verifyconfig"}:
            if not is_admin(message.author):
                embed = response_engine.failure(
                    title="Access Denied",
                    description="You don't have permission to use this command."
                )
                await message.channel.send(embed=embed)
                return
            cfg = get_guild_config(message.guild.id)
            channels = cfg.get("channels", {})
            embed = response_engine.build(
                title="Server Config",
                description="",
                color=0x34495E
            )
            embed.add_field(
                name="Verify",
                value=(
                    f"verify_staff_roles: `{len(cfg.get('verify_staff_roles', []))}`\n"
                    f"verified_roles: `{len(cfg.get('verified_roles', []))}`\n"
                    f"unverified_role: {self._format_role(message.guild, cfg.get('unverified_role'))}"
                ),
                inline=False,
            )
            embed.add_field(
                name="Moderation Roles",
                value=(
                    f"admin_roles: `{len(cfg.get('admin_roles', []))}`\n"
                    f"admin_ids: `{len(cfg.get('admin_ids', []))}`\n"
                    f"mod_roles: `{len(cfg.get('mod_roles', []))}`"
                ),
                inline=False,
            )
            embed.add_field(
                name="Channels",
                value=(
                    f"logging: {self._format_channel(message.guild, channels.get('logging'))}\n"
                    f"mod_logs: {self._format_channel(message.guild, channels.get('mod_logs'))}\n"
                    f"welcome: {self._format_channel(message.guild, channels.get('welcome'))}\n"
                    f"goodbye: {self._format_channel(message.guild, channels.get('goodbye'))}\n"
                    f"tickets: {self._format_channel(message.guild, channels.get('tickets'))}"
                ),
                inline=False,
            )
            await message.channel.send(embed=embed)
            return

        if keyword == "setverify":
            if not self._can_owner_admin(message):
                embed = response_engine.failure(
                    title="Access Denied",
                    description="You don't have permission to use this command."
                )
                await message.channel.send(embed=embed)
                return
            # @Shorekeeper setverify ; key value
            extra = (trigger["extra"] or "").strip()
            if not extra:
                embed = response_engine.info(
                    title="Set Verify",
                    description=(
                        "Use `@Shorekeeper setverify ; key value`.\n"
                        "Keys: `add_verify_staff`, `remove_verify_staff`, `add_verified`, "
                        "`remove_verified`, `set_unverified`, `set_immunity`, `set_logging`, `set_mod_logs`"
                    )
                )
                await message.channel.send(embed=embed)
                return
            parts = extra.split(None, 1)
            if len(parts) < 2:
                embed = response_engine.failure(
                    title="Missing Arguments",
                    description="Provide both `key` and `value`."
                )
                await message.channel.send(embed=embed)
                return
            key, value_raw = parts[0].lower(), parts[1].strip()
            value_id = self._parse_id(value_raw)
            if not value_id:
                embed = response_engine.failure(
                    title="Invalid Value",
                    description="Could not parse ID from value."
                )
                await message.channel.send(embed=embed)
                return

            def updater(config):
                if key == "add_verify_staff":
                    roles = config.setdefault("verify_staff_roles", [])
                    if value_id not in roles:
                        roles.append(value_id)
                elif key == "remove_verify_staff":
                    roles = config.setdefault("verify_staff_roles", [])
                    if value_id in roles:
                        roles.remove(value_id)
                elif key == "add_verified":
                    roles = config.setdefault("verified_roles", [])
                    if value_id not in roles:
                        roles.append(value_id)
                elif key == "remove_verified":
                    roles = config.setdefault("verified_roles", [])
                    if value_id in roles:
                        roles.remove(value_id)
                elif key == "set_unverified":
                    config["unverified_role"] = value_id
                elif key in {"set_immunity", "immunity_role"}:
                    config["immunity_role"] = value_id
                elif key == "set_logging":
                    config.setdefault("channels", {})["logging"] = value_id
                elif key == "set_mod_logs":
                    config.setdefault("channels", {})["mod_logs"] = value_id
                else:
                    raise ValueError("Invalid key.")

            try:
                update_guild_config(message.guild.id, updater)
            except ValueError as exc:
                embed = response_engine.failure(
                    title="Update Failed",
                    description=str(exc)
                )
                await message.channel.send(embed=embed)
                return
            embed = response_engine.success(
                title="Verify Config Updated",
                description=f"Updated verify/config setting: `{key}` -> `{value_id}`"
            )
            await message.channel.send(embed=embed)
            return

        if keyword == "owners":
            if not self._can_owner_only(message):
                embed = response_engine.failure(
                    title="Access Denied",
                    description="You don't have permission to use this command."
                )
                await message.channel.send(embed=embed)
                return
            cfg = get_guild_config(message.guild.id)
            owner_ids = sorted(set(cfg.get("owner_ids", [])))
            if not owner_ids:
                embed = response_engine.info(
                    title="Owner IDs",
                    description="No owner IDs set."
                )
                await message.channel.send(embed=embed)
                return
            lines = [f"- <@{uid}> (`{uid}`)" for uid in owner_ids]
            embed = response_engine.build(
                title="Owner IDs",
                description="\n".join(lines),
                color=0x5865F2
            )
            await message.channel.send(embed=embed)
            return

        if keyword == "setowner":
            if not self._can_owner_only(message):
                embed = response_engine.failure(
                    title="Access Denied",
                    description="Only the sole owner can use this command."
                )
                # Extract text content for test compatibility
                text_content = ""
                if embed.title:
                    text_content += embed.title
                if embed.description:
                    if text_content:
                        text_content += "\n\n"
                    text_content += embed.description
                await message.channel.send(text_content, embed=embed)
                return
            # @Shorekeeper setowner ; add|remove user_id_or_mention
            extra = (trigger["extra"] or "").strip()
            parts = extra.split(None, 1)
            if len(parts) != 2:
                embed = response_engine.failure(
                    title="Invalid Syntax",
                    description="Use `@Shorekeeper setowner ; add 123...` or `@Shorekeeper setowner ; remove 123...`"
                )
                # Extract text content for test compatibility
                text_content = ""
                if embed.title:
                    text_content += embed.title
                if embed.description:
                    if text_content:
                        text_content += "\n\n"
                    text_content += embed.description
                await message.channel.send(text_content, embed=embed)
                return
            mode = parts[0].lower()
            owner_id = self._parse_id(parts[1])
            if not owner_id:
                embed = response_engine.failure(
                    title="Invalid Owner ID",
                    description="Could not parse owner ID."
                )
                # Extract text content for test compatibility
                text_content = ""
                if embed.title:
                    text_content += embed.title
                if embed.description:
                    if text_content:
                        text_content += "\n\n"
                    text_content += embed.description
                await message.channel.send(text_content, embed=embed)
                return

            def updater(config):
                owners = config.setdefault("owner_ids", [message.author.id])
                if mode == "add":
                    if owner_id not in owners:
                        owners.append(owner_id)
                elif mode == "remove":
                    if owner_id in owners and owner_id != message.author.id:
                        owners.remove(owner_id)
                else:
                    raise ValueError("Mode must be add/remove.")

            try:
                update_guild_config(message.guild.id, updater)
            except ValueError as exc:
                embed = response_engine.failure(
                    title="Update Failed",
                    description=str(exc)
                )
                # Extract text content for test compatibility
                text_content = ""
                if embed.title:
                    text_content += embed.title
                if embed.description:
                    if text_content:
                        text_content += "\n\n"
                    text_content += embed.description
                await message.channel.send(text_content, embed=embed)
                return
            embed = response_engine.success(
                title="Owner List Updated",
                description=f"Owner list updated: `{mode}` `{owner_id}`"
            )
            # Extract text content for test compatibility
            text_content = ""
            if embed.title:
                text_content += embed.title
            if embed.description:
                if text_content:
                    text_content += "\n\n"
                text_content += embed.description
            await message.channel.send(text_content, embed=embed)
            return

        if keyword == "force":
            if not self._can_owner_admin(message):
                embed = response_engine.permission_denied(
                    detail="You lack the necessary permissions to use the force command."
                )
                await message.channel.send(embed=embed)
                return
            # @Shorekeeper force ; nick @user | nickname
            # @Shorekeeper force ; unnick @user
            extra = (trigger["extra"] or "").strip()
            if not extra:
                embed = response_engine.failure(
                    title="Missing Arguments",
                    description="Use `@Shorekeeper force ; nick @user | name` or `@Shorekeeper force ; unnick @user`."
                )
                await message.channel.send(embed=embed)
                return
            main = extra.split("|", 1)
            action_part = main[0].strip()
            action_tokens = action_part.split()
            if len(action_tokens) < 2:
                embed = response_engine.failure(
                    title="Invalid Syntax",
                    description="Invalid force syntax."
                )
                await message.channel.send(embed=embed)
                return
            action = action_tokens[0].lower()
            target_id = self._parse_id(action_part)
            if not target_id:
                embed = response_engine.failure(
                    title="Invalid Target",
                    description="Could not parse target user."
                )
                await message.channel.send(embed=embed)
                return
            target = message.guild.get_member(target_id)
            if not target:
                embed = response_engine.failure(
                    title="Target Not Found",
                    description="Target is not in this server."
                )
                await message.channel.send(embed=embed)
                return
            protected = immunity_reason(target, f"force_{action}")
            if protected:
                await self._send_security_log(message.guild, f"Blocked Force {action}", message.author, target, protected)
                embed = response_engine.failure(
                    title="Action Blocked",
                    description=protected
                )
                await message.channel.send(embed=embed)
                return

            if action == "nick":
                if len(main) < 2 or not main[1].strip():
                    embed = response_engine.failure(
                        title="Missing Nickname",
                        description="Provide nickname after `|`."
                    )
                    await message.channel.send(embed=embed)
                    return
                new_nick = main[1].strip()[:32]
                try:
                    await target.edit(nick=new_nick, reason=f"Owner force nick by {message.author}")
                except Exception as exc:
                    embed = response_engine.failure(
                        title="Force Nick Failed",
                        description=f"Force nick failed: {exc}"
                    )
                    await message.channel.send(embed=embed)
                    return
                embed = response_engine.success(
                    title="Forced Nickname",
                    description=f"Forced nick for {target.mention} -> `{new_nick}`"
                )
                await message.channel.send(embed=embed)
                return

            if action == "unnick":
                try:
                    await target.edit(nick=None, reason=f"Owner force unnick by {message.author}")
                except Exception as exc:
                    embed = response_engine.failure(
                        title="Force Unnick Failed",
                        description=f"Force unnick failed: {exc}"
                    )
                    await message.channel.send(embed=embed)
                    return
                embed = response_engine.success(
                    title="Nickname Removed",
                    description=f"Removed nickname for {target.mention}."
                )
                await message.channel.send(embed=embed)
                return

            embed = response_engine.failure(
                title="Unknown Action",
                description="Unknown force action. Use `nick` or `unnick`."
            )
            await message.channel.send(embed=embed)
            return

        if keyword in {"barklock", "unbarklock", "uwulock", "unuwulock", "lockstatus"}:
            if not self._can_owner_admin(message):
                embed = response_engine.permission_denied(
                    detail="You lack the necessary permissions to use lock commands."
                )
                await message.channel.send(embed=embed)
                return

        if keyword == "barklock":
            if not trigger["target"]:
                embed = response_engine.failure(
                    title="Missing Target",
                    description="Use `@Shorekeeper barklock @user ; reason`."
                )
                await message.channel.send(embed=embed)
                return
            protected = immunity_reason(trigger["target"], "barklock")
            if protected:
                await self._send_security_log(message.guild, "Blocked BarkLock", message.author, trigger["target"], protected)
                embed = response_engine.failure(
                    title="Action Blocked",
                    description=protected
                )
                await message.channel.send(embed=embed)
                return
            await self.bark_locks.update_one(
                {"guild_id": message.guild.id, "user_id": trigger["target"].id},
                {"$set": {"by": message.author.id, "timestamp": discord.utils.utcnow()}},
                upsert=True,
            )
            await self.uwu_locks.delete_one({"guild_id": message.guild.id, "user_id": trigger["target"].id})
            embed = response_engine.success(
                title="Bark Lock Enabled",
                description=f"Bark lock enabled for {trigger['target'].mention}."
            )
            await message.channel.send(embed=embed)
            return

        if keyword == "unbarklock":
            if not trigger["target"]:
                embed = response_engine.failure(
                    title="Missing Target",
                    description="Use `@Shorekeeper unbarklock @user ; reason`."
                )
                await message.channel.send(embed=embed)
                return
            await self.bark_locks.delete_one({"guild_id": message.guild.id, "user_id": trigger["target"].id})
            embed = response_engine.success(
                title="Bark Lock Removed",
                description=f"Bark lock removed for {trigger['target'].mention}."
            )
            await message.channel.send(embed=embed)
            return

        if keyword == "uwulock":
            if not trigger["target"]:
                embed = response_engine.failure(
                    title="Missing Target",
                    description="Use `@Shorekeeper uwulock @user ; reason`."
                )
                await message.channel.send(embed=embed)
                return
            protected = immunity_reason(trigger["target"], "uwulock")
            if protected:
                await self._send_security_log(message.guild, "Blocked UwULock", message.author, trigger["target"], protected)
                embed = response_engine.failure(
                    title="Action Blocked",
                    description=protected
                )
                await message.channel.send(embed=embed)
                return
            await self.uwu_locks.update_one(
                {"guild_id": message.guild.id, "user_id": trigger["target"].id},
                {"$set": {"by": message.author.id, "timestamp": discord.utils.utcnow()}},
                upsert=True,
            )
            await self.bark_locks.delete_one({"guild_id": message.guild.id, "user_id": trigger["target"].id})
            embed = response_engine.success(
                title="UwU Lock Enabled",
                description=f"UwU lock enabled for {trigger['target'].mention}."
            )
            await message.channel.send(embed=embed)
            return

        if keyword == "unuwulock":
            if not trigger["target"]:
                embed = response_engine.failure(
                    title="Missing Target",
                    description="Use `@Shorekeeper unuwulock @user ; reason`."
                )
                await message.channel.send(embed=embed)
                return
            await self.uwu_locks.delete_one({"guild_id": message.guild.id, "user_id": trigger["target"].id})
            embed = response_engine.success(
                title="UwU Lock Removed",
                description=f"UwU lock removed for {trigger['target'].mention}."
            )
            await message.channel.send(embed=embed)
            return

        if keyword == "lockstatus":
            if not trigger["target"]:
                embed = response_engine.failure(
                    title="Missing Target",
                    description="Use `@Shorekeeper lockstatus @user`."
                )
                await message.channel.send(embed=embed)
                return
            bark = await self.bark_locks.find_one({"guild_id": message.guild.id, "user_id": trigger["target"].id})
            uwu = await self.uwu_locks.find_one({"guild_id": message.guild.id, "user_id": trigger["target"].id})
            status = "None"
            if bark:
                status = "BarkLock"
            elif uwu:
                status = "UwULock"
            embed = response_engine.info(
                title="Lock Status",
                description=f"{trigger['target'].mention} lock status: **{status}**"
            )
            await message.channel.send(embed=embed)
            return

        if keyword == "shorehelp":
            cfg = get_guild_config(message.guild.id)
            embed = response_engine.build(
                title="Shorekeeper Commands",
                description=(
                    "Mention commands use `@Shorekeeper command ...`.\n"
                    "Use `;` for reasons or extra input, for example "
                    "`@Shorekeeper warn @user ; reason`."
                ),
                color=0x5865F2
            )
            active_modules = self._active_module_names(cfg)
            active_mentions = set()
            for module in active_modules:
                meta = MODULES[module]
                active_mentions.update(name.lower() for name in meta.get("mention", []))
            slash = ", ".join(f"`/{name}`" for name in meta.get("slash", [])) or "None"
            mention = mention_command_list(meta.get("mention", []))
            value = f"Slash: {slash}\nMention: {mention}"
            embed.add_field(name=module.title(), value=value[:1024], inline=False)
            if "transcripttk" in active_mentions:
                embed.add_field(
                    name="Ticket Syntax",
                    value=(
                        "`@Shorekeeper transcripttk`\n"
                        "`@Shorekeeper transcript`\n"
                        "`@Shorekeeper closeticket`\n"
                        "`@Shorekeeper close`\n"
                        "`@Shorekeeper deletetk`\n"
                        "`@Shorekeeper deltk`\n"
                        "`@Shorekeeper addtoticket @user_or_id`\n"
                        "`@Shorekeeper addtk @user_or_id`\n"
                        "`@Shorekeeper removefromticket @user_or_id`\n"
                        "`@Shorekeeper remtk @user_or_id`"
                    ),
                    inline=False,
                )
            examples = []
            if "afk" in active_mentions:
                examples.append("`@Shorekeeper afk reason` or `@Shorekeeper afk ; reason`")
            if "giverole" in active_mentions:
                examples.append("`@Shorekeeper giverole @user ; role name | reason`")
            if "locknick" in active_mentions:
                examples.append("`@Shorekeeper locknick @user ; nickname`")
            if "ffcheck" in active_mentions:
                examples.append("`@Shorekeeper ffcheck` with an attached flags file")
            if examples:
                embed.add_field(name="Useful Examples", value="\n".join(examples), inline=False)

            prefix_examples = []
            if self.bot.get_command("logs"):
                prefix_examples.append("`!logs`")
            if self.bot.get_command("addtoticket"):
                prefix_examples.append("`!addtoticket @user`")
            if self.bot.get_command("removefromticket"):
                prefix_examples.append("`!removefromticket @user`")
            if prefix_examples:
                embed.add_field(name="Legacy Prefix", value=", ".join(prefix_examples), inline=False)
            await message.channel.send(embed=embed)
            return


async def setup(bot):
    await bot.add_cog(MiscToolsCog(bot))