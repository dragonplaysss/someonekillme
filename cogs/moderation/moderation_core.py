import datetime
import re

import discord
from discord.ext import commands

from cogs.core.authz import DangerousActionRequest, authorize_dangerous_action
from cogs.core.cases import CaseService
from cogs.core.responses import response_engine
from cogs.server_config import get_channel_id, get_guild_config, immunity_reason, is_admin, is_mod
from cogs.trigger_parser import parse_shorekeeper_trigger
from cogs.mongo_client import get_mongo_database, safe_create_index


class ModerationCore(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db = get_mongo_database()
        self.warns = self.db["warns"]
        self.mod_actions = self.db["mod_actions"]
        self.cases = CaseService(self.db)

    def is_admin(self, member):
        return is_admin(member)

    def is_mod(self, member):
        return is_mod(member)

    def parse_duration(self, content):
        match = re.search(r"(\d+)([smhd])", content)
        if not match:
            return datetime.timedelta(minutes=10)

        amount, unit = int(match.group(1)), match.group(2)
        units = {"s": "seconds", "m": "minutes", "h": "hours", "d": "days"}
        return datetime.timedelta(**{units[unit]: amount})

    async def cog_load(self):
        # Index setup must never abort cog loading: if it did, the whole
        # moderation listener would silently disappear and mention commands
        # (kick/ban/warn/...) would parse correctly but never execute.
        await safe_create_index(self.warns, [("guild_id", 1), ("user_id", 1)])
        await safe_create_index(self.mod_actions, [("guild_id", 1), ("timestamp", -1)])
        try:
            await self.cases.ensure_indexes()
        except Exception as exc:  # noqa: BLE001
            print(f"[MODERATION] case index setup failed: {type(exc).__name__}: {exc}")

    async def send_mod_dm(self, target, guild, action, reason):
        if not isinstance(target, (discord.Member, discord.User)):
            return
        embed = response_engine.build(
            title="Moderation Notice",
            description="A moderation action was taken in a server you are in.",
            color=discord.Color.orange()
        )
        embed.add_field(name="Server", value=guild.name, inline=False)
        embed.add_field(name="Action", value=action, inline=True)
        embed.add_field(name="Reason", value=reason, inline=False)
        try:
            await target.send(embed=embed)
        except Exception:
            pass

    async def send_mod_log(self, guild, action, moderator, target_label, reason):
        mod_logs_id = get_channel_id(guild.id, "mod_logs") or get_channel_id(guild.id, "logging")
        channel = guild.get_channel(mod_logs_id) if mod_logs_id else None
        if not channel:
            return
        embed = response_engine.build(
            title=f"Moderation: {action}",
            description="A moderation action has been logged.",
            color=0xE74C3C
        )
        embed.add_field(name="Target", value=target_label, inline=False)
        embed.add_field(name="Moderator", value=moderator.mention, inline=True)
        embed.add_field(name="Reason", value=reason, inline=False)
        await channel.send(embed=embed)

    async def persist_action(self, guild_id, moderator_id, target_id, action, reason):
        await self.mod_actions.insert_one(
            {
                "guild_id": guild_id,
                "moderator_id": moderator_id,
                "target_id": target_id,
                "action": action,
                "reason": reason,
                "timestamp": discord.utils.utcnow(),
            }
        )

    async def create_moderation_case(self, guild_id, action, target_id, moderator_id, reason, evidence=None):
        service = getattr(self, "cases", None)
        if service is None or target_id is None:
            return None
        return await service.create_case(
            guild_id=guild_id,
            action=action,
            target_id=target_id,
            moderator_id=moderator_id,
            reason=reason,
            evidence=evidence,
        )

    def authorize_member_action(
        self,
        message,
        *,
        action: str,
        target,
        actor_authorized: bool,
        required_actor_permissions=(),
        required_bot_permissions=(),
    ):
        bot_member = message.guild.me or message.guild.get_member(self.bot.user.id)
        return authorize_dangerous_action(
            DangerousActionRequest(
                guild_config=get_guild_config(message.guild.id),
                module="moderation",
                actor=message.author,
                bot_member=bot_member,
                target_member=target,
                target_role=None,
                actor_authorized=actor_authorized,
                required_bot_permissions=required_bot_permissions,
                required_actor_permissions=required_actor_permissions,
                security_policy_allowed=True,
                security_action=action,
            )
        )

    async def deny_authorization(self, message, decision):
        detail = decision.reason or "Action denied by Shorekeeper's safety checks."
        if decision.stage in {"actor_hierarchy", "bot_hierarchy"}:
            embed = response_engine.hierarchy_denied(detail)
        else:
            embed = response_engine.permission_denied(detail)
        await message.channel.send(embed=embed)

    async def block_if_immune(self, message, target, target_id, action):
        protected = target if target is not None else target_id
        reason = immunity_reason(protected, action)
        if not reason:
            return False
        target_label = f"{target.mention} ({target.id})" if target else f"<@{target_id}> ({target_id})"
        await self.send_mod_log(message.guild, f"Blocked {action.title()}", message.author, target_label, reason)
        await self.persist_action(message.guild.id, message.author.id, target_id, f"blocked_{action}", reason)
        embed = response_engine.failure(
            title="Action Blocked",
            description=reason
        )
        await message.channel.send(embed=embed)
        return True

    @commands.Cog.listener()
    async def on_message(self, message):
        try:
            await self.handle_message(message)
        except Exception as e:
            print(f"[ModerationCore Error] {type(e).__name__}: {e}")
            try:
                embed = response_engine.failure(
                    title="Moderation Handler Error",
                    description=f"{type(e).__name__}: {e}"
                )
                await message.channel.send(embed=embed)
            except Exception:
                pass

    async def handle_message(self, message):
        trigger = parse_shorekeeper_trigger(self.bot, message)
        if not trigger:
            return

        keyword = trigger["keyword"]
        target = trigger["target"]
        target_id = trigger["target_id"]
        reason = trigger["extra"] or "No reason."

        is_admin = self.is_admin(message.author)
        is_mod = self.is_mod(message.author)

        if keyword == "modtest":
            embed = response_engine.info(
                title="Moderation Core Status",
                description=f"admin={is_admin} mod={is_mod}"
            )
            await message.channel.send(embed=embed)
            return

        if keyword == "ban":
            if not is_admin:
                embed = response_engine.permission_denied(
                    detail="No permission."
                )
                await message.channel.send(embed=embed)
                return
            if not target_id:
                embed = response_engine.failure(
                    title="Missing Argument",
                    description="Use `@Shorekeeper ban @user ; reason`."
                )
                await message.channel.send(embed=embed)
                return
            if await self.block_if_immune(message, target, target_id, "ban"):
                return
            if target:
                decision = self.authorize_member_action(
                    message,
                    action="ban",
                    target=target,
                    actor_authorized=is_admin,
                    required_actor_permissions=("ban_members",),
                    required_bot_permissions=("ban_members",),
                )
                if not decision.allowed:
                    return await self.deny_authorization(message, decision)

            try:
                ban_target = target or discord.Object(id=target_id)
                await message.guild.ban(ban_target, reason=reason)

                target_label = f"{target.mention} ({target.id})" if target else f"<@{target_id}> ({target_id})"
                await self.send_mod_dm(target, message.guild, "Ban", reason)
                await self.send_mod_log(message.guild, "Ban", message.author, target_label, reason)
                await self.persist_action(message.guild.id, message.author.id, target_id, "ban", reason)
                case = await self.create_moderation_case(message.guild.id, "BAN", target_id, message.author.id, reason)
                suffix = f" Case #{case['case_id']}." if case else ""
                embed = response_engine.success(
                    title="Ban Successful",
                    description=f"Banned {target_label}.{suffix}"
                )
                await message.channel.send(embed=embed)
            except Exception as e:
                embed = response_engine.failure(
                    title="Ban Failed",
                    description=f"{e}"
                )
                await message.channel.send(embed=embed)

        elif keyword == "kick":
            if not is_mod:
                embed = response_engine.permission_denied(
                    detail="No permission."
                )
                await message.channel.send(embed=embed)
                return
            if not target:
                embed = response_engine.failure(
                    title="Missing Argument",
                    description="Mention a user to kick."
                )
                await message.channel.send(embed=embed)
                return
            if await self.block_if_immune(message, target, target.id, "kick"):
                return
            decision = self.authorize_member_action(
                message,
                action="kick",
                target=target,
                actor_authorized=is_mod,
                required_actor_permissions=("kick_members",),
                required_bot_permissions=("kick_members",),
            )
            if not decision.allowed:
                return await self.deny_authorization(message, decision)

            try:
                await target.kick(reason=reason)
                await self.send_mod_dm(target, message.guild, "Kick", reason)
                await self.send_mod_log(
                    message.guild, "Kick", message.author, f"{target.mention} ({target.id})", reason
                )
                await self.persist_action(message.guild.id, message.author.id, target.id, "kick", reason)
                case = await self.create_moderation_case(message.guild.id, "KICK", target.id, message.author.id, reason)
                suffix = f" Case #{case['case_id']}." if case else ""
                embed = response_engine.success(
                    title="Kick Successful",
                    description=f"Kicked {target.mention}.{suffix}"
                )
                await message.channel.send(embed=embed)
            except Exception as e:
                embed = response_engine.failure(
                    title="Kick Failed",
                    description=f"{e}"
                )
                await message.channel.send(embed=embed)

        elif keyword == "unban":
            if not is_admin:
                embed = response_engine.permission_denied(
                    detail="No permission."
                )
                await message.channel.send(embed=embed)
                return
            if not target_id:
                embed = response_engine.failure(
                    title="Missing Argument",
                    description="Use `@Shorekeeper unban @user_or_id ; reason`."
                )
                await message.channel.send(embed=embed)
                return
            decision = authorize_dangerous_action(
                DangerousActionRequest(
                    guild_config=get_guild_config(message.guild.id),
                    module="moderation",
                    actor=message.author,
                    bot_member=message.guild.me or message.guild.get_member(self.bot.user.id),
                    target_member=None,
                    target_role=None,
                    actor_authorized=is_admin,
                    required_bot_permissions=("ban_members",),
                    required_actor_permissions=("ban_members",),
                    security_policy_allowed=True,
                    security_action="unban",
                )
            )
            if not decision.allowed:
                return await self.deny_authorization(message, decision)

            try:
                await message.guild.unban(discord.Object(id=target_id), reason=reason)
                await self.send_mod_log(
                    message.guild, "Unban", message.author, f"<@{target_id}> ({target_id})", reason
                )
                await self.persist_action(message.guild.id, message.author.id, target_id, "unban", reason)
                case = await self.create_moderation_case(message.guild.id, "UNBAN", target_id, message.author.id, reason)
                suffix = f" Case #{case['case_id']}." if case else ""
                embed = response_engine.success(
                    title="Unban Successful",
                    description=f"Unbanned `{target_id}`.{suffix}"
                )
                await message.channel.send(embed=embed)
            except discord.NotFound:
                embed = response_engine.failure(
                    title="Unban Failed",
                    description="That user is not banned."
                )
                await message.channel.send(embed=embed)
            except Exception as e:
                embed = response_engine.failure(
                    title="Unban Failed",
                    description=f"{e}"
                )
                await message.channel.send(embed=embed)

        elif keyword == "mute":
            if not is_mod:
                embed = response_engine.permission_denied(
                    detail="No permission."
                )
                await message.channel.send(embed=embed)
                return
            if not target:
                embed = response_engine.failure(
                    title="Missing Argument",
                    description="Use `@Shorekeeper mute @user ; reason`."
                )
                await message.channel.send(embed=embed)
                return
            if await self.block_if_immune(message, target, target.id, "mute"):
                return
            decision = self.authorize_member_action(
                message,
                action="mute",
                target=target,
                actor_authorized=is_mod,
                required_actor_permissions=("moderate_members",),
                required_bot_permissions=("moderate_members",),
            )
            if not decision.allowed:
                return await self.deny_authorization(message, decision)

            try:
                duration = self.parse_duration(trigger["main"])
                await target.timeout(discord.utils.utcnow() + duration, reason=reason)
                await self.send_mod_dm(target, message.guild, "Mute", reason)
                await self.send_mod_log(
                    message.guild, "Mute", message.author, f"{target.mention} ({target.id})", reason
                )
                await self.persist_action(message.guild.id, message.author.id, target.id, "mute", reason)
                case = await self.create_moderation_case(message.guild.id, "TIMEOUT", target.id, message.author.id, reason)
                suffix = f" Case #{case['case_id']}." if case else ""
                embed = response_engine.success(
                    title="Mute Successful",
                    description=f"Muted {target.mention} for {duration}.{suffix}"
                )
                await message.channel.send(embed=embed)
            except Exception as e:
                embed = response_engine.failure(
                    title="Mute Failed",
                    description=f"{e}"
                )
                await message.channel.send(embed=embed)

        elif keyword in {"unmute", "untimeout"}:
            if not is_mod:
                embed = response_engine.permission_denied(
                    detail="No permission."
                )
                await message.channel.send(embed=embed)
                return
            if not target:
                embed = response_engine.failure(
                    title="Missing Argument",
                    description="Use `@Shorekeeper unmute @user ; reason`."
                )
                await message.channel.send(embed=embed)
                return
            if await self.block_if_immune(message, target, target.id, "unmute"):
                return
            decision = self.authorize_member_action(
                message,
                action="unmute",
                target=target,
                actor_authorized=is_mod,
                required_actor_permissions=("moderate_members",),
                required_bot_permissions=("moderate_members",),
            )
            if not decision.allowed:
                return await self.deny_authorization(message, decision)

            try:
                await target.timeout(None, reason=reason)
                await self.send_mod_log(
                    message.guild, "Unmute", message.author, f"{target.mention} ({target.id})", reason
                )
                await self.persist_action(message.guild.id, message.author.id, target.id, "unmute", reason)
                case = await self.create_moderation_case(
                    message.guild.id, "UNTIMEOUT", target.id, message.author.id, reason
                )
                suffix = f" Case #{case['case_id']}." if case else ""
                embed = response_engine.success(
                    title="Unmute Successful",
                    description=f"Unmuted {target.mention}.{suffix}"
                )
                await message.channel.send(embed=embed)
            except Exception as e:
                embed = response_engine.failure(
                    title="Unmute Failed",
                    description=f"{e}"
                )
                await message.channel.send(embed=embed)

        elif keyword == "warn":
            if not is_mod:
                embed = response_engine.permission_denied(
                    detail="No permission."
                )
                await message.channel.send(embed=embed)
                return
            if not target:
                embed = response_engine.failure(
                    title="Missing Argument",
                    description="Use `@Shorekeeper warn @user ; reason`."
                )
                await message.channel.send(embed=embed)
                return
            if await self.block_if_immune(message, target, target.id, "warn"):
                return
            decision = self.authorize_member_action(
                message,
                action="warn",
                target=target,
                actor_authorized=is_mod,
                required_actor_permissions=(),
                required_bot_permissions=(),
            )
            if not decision.allowed:
                return await self.deny_authorization(message, decision)

            await self.warns.insert_one(
                {
                    "guild_id": message.guild.id,
                    "user_id": target.id,
                    "moderator_id": message.author.id,
                    "reason": reason,
                    "timestamp": discord.utils.utcnow(),
                }
            )
            count = await self.warns.count_documents(
                {"guild_id": message.guild.id, "user_id": target.id}
            )
            await self.send_mod_dm(target, message.guild, "Warn", reason)
            await self.send_mod_log(
                message.guild,
                "Warn",
                message.author,
                f"{target.mention} ({target.id})",
                f"{reason}\nTotal warns: {count}",
            )
            await self.persist_action(message.guild.id, message.author.id, target.id, "warn", reason)
            case = await self.create_moderation_case(message.guild.id, "WARN", target.id, message.author.id, reason)
            suffix = f" Case #{case['case_id']}." if case else ""
            embed = response_engine.success(
                title="Warn Successful",
                description=f"Warned {target.mention}. Total warns: `{count}`{suffix}"
            )
            await message.channel.send(embed=embed)

        elif keyword == "purge":
            if not is_mod:
                embed = response_engine.permission_denied(
                    detail="No permission."
                )
                await message.channel.send(embed=embed)
                return

            amount = None
            for token in trigger.get("args") or []:
                if str(token).isdigit():
                    amount = int(token)
                    break
            if amount is None:
                embed = response_engine.failure(
                    title="Missing Argument",
                    description="Use `@Shorekeeper purge 25`."
                )
                await message.channel.send(embed=embed)
                return

            if amount <= 0:
                embed = response_engine.failure(
                    title="Invalid Amount",
                    description="Purge amount must be greater than zero."
                )
                await message.channel.send(embed=embed)
                return

            decision = authorize_dangerous_action(
                DangerousActionRequest(
                    guild_config=get_guild_config(message.guild.id),
                    module="moderation",
                    actor=message.author,
                    bot_member=message.guild.me or message.guild.get_member(self.bot.user.id),
                    target_member=None,
                    target_role=None,
                    actor_authorized=is_mod,
                    required_bot_permissions=("manage_messages",),
                    required_actor_permissions=("manage_messages",),
                    security_policy_allowed=True,
                    security_action="purge",
                )
            )

            if not decision.allowed:
                return await self.deny_authorization(message, decision)

            try:
                await message.channel.purge(limit=amount)
                await self.persist_action(message.guild.id, message.author.id, message.channel.id, "purge", f"Deleted {amount}")
                case = await self.create_moderation_case(
                    message.guild.id, "PURGE", message.channel.id, message.author.id, f"Deleted {amount} messages"
                )
                suffix = f" Case #{case['case_id']}." if case else ""
                embed = response_engine.success(
                    title="Purge Successful",
                    description=f"Deleted {amount} messages.{suffix}"
                )
                await message.channel.send(embed=embed, delete_after=3)
            except Exception as e:
                embed = response_engine.failure(
                    title="Purge Failed",
                    description=f"{e}"
                )
                await message.channel.send(embed=embed)

        elif keyword in {"lock", "unlock", "slowmode", "case", "cases"}:
            await self._handle_extended(message, trigger, keyword, is_mod)

    async def _handle_extended(self, message, trigger, keyword, is_mod):
        bot_member = message.guild.me or message.guild.get_member(self.bot.user.id)
        if keyword == "case":
            if not is_mod:
                embed = response_engine.permission_denied(
                    detail="No permission."
                )
                await message.channel.send(embed=embed)
                return
            case_id = None
            for token in trigger.get("args") or []:
                if str(token).isdigit():
                    case_id = int(token)
                    break
            if case_id is None:
                embed = response_engine.failure(
                    title="Missing Argument",
                    description="Use `@Shorekeeper case 1042`."
                )
                await message.channel.send(embed=embed)
                return
            service = getattr(self, "cases", None)
            doc = await service.find_case(message.guild.id, case_id) if service else None
            if not doc:
                embed = response_engine.failure(
                    title="Case Not Found",
                    description="That case was not found."
                )
                await message.channel.send(embed=embed)
                return
            await message.channel.send(
                embed=response_engine.case_result(
                    doc["case_id"],
                    f"Target: <@{doc['target_id']}>\nModerator: <@{doc['moderator_id']}>\nAction: `{doc['action']}`\nReason: {doc.get('reason')}",
                )
            )
        if keyword == "cases":
            if not is_mod:
                embed = response_engine.permission_denied(
                    detail="No permission."
                )
                await message.channel.send(embed=embed)
                return
            target = trigger.get("target")
            target_id = trigger.get("target_id") or (target.id if target else None)
            if not target_id:
                embed = response_engine.failure(
                    title="Missing Argument",
                    description="Use `@Shorekeeper cases @user`."
                )
                await message.channel.send(embed=embed)
                return
            service = getattr(self, "cases", None)
            docs = await service.find_cases(message.guild.id, target_id) if service else []
            if not docs:
                embed = response_engine.failure(
                    title="No Cases Found",
                    description="No cases found for that member."
                )
                await message.channel.send(embed=embed)
                return
            lines = [f"#{doc['case_id']} `{doc['action']}` — {doc.get('reason')}" for doc in docs]
            await message.channel.send(embed=response_engine.moderation_result("Moderation Cases", "\n".join(lines)[:4000]))

        if keyword in {"lock", "unlock", "slowmode"}:
            if not is_mod:
                embed = response_engine.permission_denied(
                    detail="No permission."
                )
                await message.channel.send(embed=embed)
                return
            channel = trigger.get("channel") or message.channel
            decision = authorize_dangerous_action(
                DangerousActionRequest(
                    guild_config=get_guild_config(message.guild.id),
                    module="moderation",
                    actor=message.author,
                    bot_member=bot_member,
                    target_member=None,
                    target_role=None,
                    actor_authorized=is_mod,
                    required_bot_permissions=("manage_channels",),
                    required_actor_permissions=("manage_channels",),
                    security_policy_allowed=True,
                    security_action=keyword,
                )
            )
            if not decision.allowed:
                return await self.deny_authorization(message, decision)
            try:
                if keyword in {"lock", "unlock"}:
                    overwrite = channel.overwrites_for(message.guild.default_role)
                    overwrite.send_messages = False if keyword == "lock" else None
                    await channel.set_permissions(message.guild.default_role, overwrite=overwrite, reason=trigger.get("extra") or keyword)
                    await self.persist_action(message.guild.id, message.author.id, channel.id, keyword, trigger.get("extra") or keyword)
                    await message.channel.send(embed=response_engine.moderation_result(keyword.title(), f"{channel.mention} has been {keyword}ed."))
                seconds = 0
                for token in trigger.get("args") or []:
                    from cogs.core.parser import parse_duration_token
                    parsed = parse_duration_token(token)
                    if parsed is not None:
                        seconds = min(int(parsed), 21600)
                        break
                    if str(token).isdigit():
                        seconds = min(int(token), 21600)
                        break
                await channel.edit(slowmode_delay=seconds, reason=trigger.get("extra") or "slowmode")
                await self.persist_action(message.guild.id, message.author.id, channel.id, "slowmode", str(seconds))
                await message.channel.send(embed=response_engine.moderation_result("Slowmode", f"{channel.mention} delay is now `{seconds}s`."))
            except Exception as exc:
                embed = response_engine.failure(
                    title=f"{keyword.title()} Failed",
                    description=f"{exc}"
                )
                await message.channel.send(embed=embed)


async def setup(bot):
    await bot.add_cog(ModerationCore(bot))