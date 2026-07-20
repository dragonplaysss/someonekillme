import datetime
import random
import re

import discord
from discord.ext import commands

from cogs.mongo_client import get_mongo_database
from cogs.module_registry import MODULES, get_module_state, mention_command_list
from cogs.server_config import get_guild_config, is_admin, is_owner_id, is_panel_owner, update_guild_config
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
        cached_id = self.webhook_cache.get(channel.id)
        try:
            webhooks = await channel.webhooks()
        except Exception:
            return None

        if cached_id:
            for hook in webhooks:
                if hook.id == cached_id:
                    return hook

        for hook in webhooks:
            if hook.name == "Shorekeeper Relay":
                self.webhook_cache[channel.id] = hook.id
                return hook

        try:
            hook = await channel.create_webhook(name="Shorekeeper Relay")
            self.webhook_cache[channel.id] = hook.id
            return hook
        except Exception:
            return None

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

    async def _enforce_fun_locks(self, message: discord.Message):
        if message.author.bot:
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

    def _can_edit_nick(self, member: discord.Member):
        bot_member = member.guild.me or member.guild.get_member(self.bot.user.id)
        if not bot_member or not bot_member.guild_permissions.manage_nicknames:
            return False
        if member == member.guild.owner:
            return False
        return member.top_role < bot_member.top_role

    async def _set_afk_nick(self, member: discord.Member):
        if not self._can_edit_nick(member):
            return None, False

        original_nick = member.nick
        display_name = member.display_name
        if display_name.upper().startswith("[AFK]"):
            return original_nick, True

        new_nick = f"[AFK] {display_name}"[:32]
        try:
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

        await message.channel.send(
            f"{label} is AFK{suffix}: {reason}",
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
            return await message.channel.send(
                f"{message.author.mention} is now AFK: {reason[:500]}{suffix}",
                allowed_mentions=discord.AllowedMentions.none(),
                delete_after=self.afk_notice_delete_after,
            )

        existing_afk = await self.afk.find_one({"guild_id": message.guild.id, "user_id": message.author.id})
        if existing_afk:
            await self._restore_afk_nick(message.author, existing_afk.get("original_nick"))
            await self.afk.delete_one({"guild_id": message.guild.id, "user_id": message.author.id})
            await message.channel.send(
                f"Welcome back {message.author.mention}. I removed your AFK.",
                allowed_mentions=discord.AllowedMentions.none(),
                delete_after=self.afk_notice_delete_after,
            )

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
            return await self._notify_afk_target(message, user_id, afk_status)

        if not trigger:
            return

        keyword = trigger["keyword"]
        target = trigger["target"] or message.author

        if keyword == "ping":
            return await message.channel.send(f"Pong! `{round(self.bot.latency * 1000)}ms`")

        if keyword == "avatar":
            embed = discord.Embed(title=f"{target} Avatar", color=0x95A5A6)
            embed.set_image(url=target.display_avatar.url)
            return await message.channel.send(embed=embed)

        if keyword == "serverinfo":
            guild = message.guild
            embed = discord.Embed(title=f"{guild.name} Server Info", color=0x5865F2)
            embed.add_field(name="Members", value=str(guild.member_count), inline=True)
            embed.add_field(name="Channels", value=str(len(guild.channels)), inline=True)
            embed.add_field(name="Roles", value=str(len(guild.roles)), inline=True)
            embed.add_field(name="Owner", value=guild.owner.mention if guild.owner else "Unknown", inline=False)
            if guild.icon:
                embed.set_thumbnail(url=guild.icon.url)
            return await message.channel.send(embed=embed)

        if keyword == "userinfo":
            member = target if isinstance(target, discord.Member) else message.guild.get_member(target.id)
            if not member:
                return await message.channel.send("Member not found.")
            embed = discord.Embed(title=f"{member} User Info", color=0x2ECC71)
            embed.add_field(name="ID", value=str(member.id), inline=True)
            embed.add_field(name="Joined", value=discord.utils.format_dt(member.joined_at, "R"), inline=True)
            embed.add_field(name="Created", value=discord.utils.format_dt(member.created_at, "R"), inline=True)
            embed.add_field(name="Top Role", value=member.top_role.mention, inline=False)
            embed.set_thumbnail(url=member.display_avatar.url)
            return await message.channel.send(embed=embed)

        if keyword == "warns":
            count = await self.warns.count_documents({"guild_id": message.guild.id, "user_id": target.id})
            return await message.channel.send(f"{target.mention} has `{count}` warn(s).")

        if keyword == "whoami":
            cfg = get_guild_config(message.guild.id)
            owner_ids = set(cfg.get("owner_ids", []))
            admin_ids = set(cfg.get("admin_ids", []))
            admin_roles = set(cfg.get("admin_roles", []))
            mod_roles = set(cfg.get("mod_roles", []))
            my_role_ids = {role.id for role in message.author.roles}
            embed = discord.Embed(title="Permission Check", color=0x1ABC9C)
            embed.add_field(name="User", value=f"{message.author.mention} (`{message.author.id}`)", inline=False)
            embed.add_field(name="is_panel_owner", value=str(is_panel_owner(message.author.id)), inline=True)
            embed.add_field(name="is_owner_id", value=str(is_owner_id(message.guild.id, message.author.id)), inline=True)
            embed.add_field(name="is_admin", value=str(is_admin(message.author)), inline=True)
            embed.add_field(name="is_mod", value=str(message.author.guild_permissions.administrator or bool(my_role_ids & mod_roles or my_role_ids & admin_roles)), inline=True)
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
            return await message.channel.send(embed=embed)

        if keyword in {"config", "showconfig", "verifyconfig"}:
            if not is_admin(message.author):
                return await message.channel.send("No permission.")
            cfg = get_guild_config(message.guild.id)
            channels = cfg.get("channels", {})
            embed = discord.Embed(title="Server Config", color=0x34495E)
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
            return await message.channel.send(embed=embed)

        if keyword == "setverify":
            if not self._can_owner_admin(message):
                return await message.channel.send("No permission.")
            # @Shorekeeper setverify ; key value
            extra = (trigger["extra"] or "").strip()
            if not extra:
                return await message.channel.send(
                    "Use `@Shorekeeper setverify ; key value`.\n"
                    "Keys: `add_verify_staff`, `remove_verify_staff`, `add_verified`, "
                    "`remove_verified`, `set_unverified`, `set_logging`, `set_mod_logs`"
                )
            parts = extra.split(None, 1)
            if len(parts) < 2:
                return await message.channel.send("Provide both `key` and `value`.")
            key, value_raw = parts[0].lower(), parts[1].strip()
            value_id = self._parse_id(value_raw)
            if not value_id:
                return await message.channel.send("Could not parse ID from value.")

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
                elif key == "set_logging":
                    config.setdefault("channels", {})["logging"] = value_id
                elif key == "set_mod_logs":
                    config.setdefault("channels", {})["mod_logs"] = value_id
                else:
                    raise ValueError("Invalid key.")

            try:
                update_guild_config(message.guild.id, updater)
            except ValueError as exc:
                return await message.channel.send(str(exc))
            return await message.channel.send(f"Updated verify/config setting: `{key}` -> `{value_id}`")

        if keyword == "owners":
            if not self._can_owner_only(message):
                return await message.channel.send("No permission.")
            cfg = get_guild_config(message.guild.id)
            owner_ids = sorted(set(cfg.get("owner_ids", [])))
            if not owner_ids:
                return await message.channel.send("No owner IDs set.")
            return await message.channel.send(
                "Owner IDs:\n" + "\n".join(f"- <@{uid}> (`{uid}`)" for uid in owner_ids)
            )

        if keyword == "setowner":
            if not self._can_owner_only(message):
                return await message.channel.send("No permission.")
            # @Shorekeeper setowner ; add|remove user_id_or_mention
            extra = (trigger["extra"] or "").strip()
            parts = extra.split(None, 1)
            if len(parts) != 2:
                return await message.channel.send(
                    "Use `@Shorekeeper setowner ; add 123...` or `@Shorekeeper setowner ; remove 123...`"
                )
            mode = parts[0].lower()
            owner_id = self._parse_id(parts[1])
            if not owner_id:
                return await message.channel.send("Could not parse owner ID.")

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
                return await message.channel.send(str(exc))
            return await message.channel.send(f"Owner list updated: `{mode}` `{owner_id}`")

        if keyword == "force":
            if not self._can_owner_admin(message):
                return await message.channel.send("No permission.")
            # @Shorekeeper force ; nick @user | nickname
            # @Shorekeeper force ; unnick @user
            extra = (trigger["extra"] or "").strip()
            if not extra:
                return await message.channel.send(
                    "Use `@Shorekeeper force ; nick @user | name` or `@Shorekeeper force ; unnick @user`."
                )
            main = extra.split("|", 1)
            action_part = main[0].strip()
            action_tokens = action_part.split()
            if len(action_tokens) < 2:
                return await message.channel.send("Invalid force syntax.")
            action = action_tokens[0].lower()
            target_id = self._parse_id(action_part)
            if not target_id:
                return await message.channel.send("Could not parse target user.")
            target = message.guild.get_member(target_id)
            if not target:
                return await message.channel.send("Target is not in this server.")

            if action == "nick":
                if len(main) < 2 or not main[1].strip():
                    return await message.channel.send("Provide nickname after `|`.")
                new_nick = main[1].strip()[:32]
                try:
                    await target.edit(nick=new_nick, reason=f"Owner force nick by {message.author}")
                except Exception as exc:
                    return await message.channel.send(f"Force nick failed: {exc}")
                return await message.channel.send(f"Forced nick for {target.mention} -> `{new_nick}`")

            if action == "unnick":
                try:
                    await target.edit(nick=None, reason=f"Owner force unnick by {message.author}")
                except Exception as exc:
                    return await message.channel.send(f"Force unnick failed: {exc}")
                return await message.channel.send(f"Removed nickname for {target.mention}.")

            return await message.channel.send("Unknown force action. Use `nick` or `unnick`.")

        if keyword in {"barklock", "unbarklock", "uwulock", "unuwulock", "lockstatus"}:
            if not self._can_owner_admin(message):
                return await message.channel.send("No permission.")

        if keyword == "barklock":
            if not trigger["target"]:
                return await message.channel.send("Use `@Shorekeeper barklock @user ; reason`.")
            await self.bark_locks.update_one(
                {"guild_id": message.guild.id, "user_id": trigger["target"].id},
                {"$set": {"by": message.author.id, "timestamp": discord.utils.utcnow()}},
                upsert=True,
            )
            await self.uwu_locks.delete_one({"guild_id": message.guild.id, "user_id": trigger["target"].id})
            return await message.channel.send(f"Bark lock enabled for {trigger['target'].mention}.")

        if keyword == "unbarklock":
            if not trigger["target"]:
                return await message.channel.send("Use `@Shorekeeper unbarklock @user ; reason`.")
            await self.bark_locks.delete_one({"guild_id": message.guild.id, "user_id": trigger["target"].id})
            return await message.channel.send(f"Bark lock removed for {trigger['target'].mention}.")

        if keyword == "uwulock":
            if not trigger["target"]:
                return await message.channel.send("Use `@Shorekeeper uwulock @user ; reason`.")
            await self.uwu_locks.update_one(
                {"guild_id": message.guild.id, "user_id": trigger["target"].id},
                {"$set": {"by": message.author.id, "timestamp": discord.utils.utcnow()}},
                upsert=True,
            )
            await self.bark_locks.delete_one({"guild_id": message.guild.id, "user_id": trigger["target"].id})
            return await message.channel.send(f"UwU lock enabled for {trigger['target'].mention}.")

        if keyword == "unuwulock":
            if not trigger["target"]:
                return await message.channel.send("Use `@Shorekeeper unuwulock @user ; reason`.")
            await self.uwu_locks.delete_one({"guild_id": message.guild.id, "user_id": trigger["target"].id})
            return await message.channel.send(f"UwU lock removed for {trigger['target'].mention}.")

        if keyword == "lockstatus":
            if not trigger["target"]:
                return await message.channel.send("Use `@Shorekeeper lockstatus @user`.")
            bark = await self.bark_locks.find_one({"guild_id": message.guild.id, "user_id": trigger["target"].id})
            uwu = await self.uwu_locks.find_one({"guild_id": message.guild.id, "user_id": trigger["target"].id})
            status = "None"
            if bark:
                status = "BarkLock"
            elif uwu:
                status = "UwULock"
            return await message.channel.send(f"{trigger['target'].mention} lock status: **{status}**")

        if keyword == "shorehelp":
            cfg = get_guild_config(message.guild.id)
            embed = discord.Embed(
                title="Shorekeeper Commands",
                description=(
                    "Mention commands use `@Shorekeeper command ...`.\n"
                    "Use `;` for reasons or extra input, for example "
                    "`@Shorekeeper warn @user ; reason`."
                ),
                color=0x5865F2,
            )
            for module, meta in MODULES.items():
                if get_module_state(cfg, module) == "disabled" or not self._module_loaded(module):
                    continue
                slash = ", ".join(f"`/{name}`" for name in meta.get("slash", [])) or "None"
                mention = mention_command_list(meta.get("mention", []))
                value = f"Slash: {slash}\nMention: {mention}"
                embed.add_field(name=module.title(), value=value[:1024], inline=False)
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
            embed.add_field(
                name="Useful Examples",
                value=(
                    "`@Shorekeeper afk reason` or `@Shorekeeper afk ; reason`\n"
                    "`@Shorekeeper giverole @user ; role name | reason`\n"
                    "`@Shorekeeper locknick @user ; nickname`\n"
                    "`@Shorekeeper ffcheck` with an attached flags file"
                ),
                inline=False,
            )
            embed.add_field(
                name="Legacy Prefix",
                value="`!logs`, `!addtoticket @user`, `!removefromticket @user`",
                inline=False,
            )
            return await message.channel.send(embed=embed)


async def setup(bot):
    await bot.add_cog(MiscToolsCog(bot))
