from __future__ import annotations

import traceback

import discord
from discord.ext import commands

from cogs.core.anti_nuke import (
    DEFAULT_THRESHOLDS,
    RateTracker,
    actor_is_allowlisted,
    actor_is_self,
    evaluate_bot_addition,
    evaluate_mass_action,
    format_allowlist,
    format_anti_nuke_status,
    guild_update_is_dangerous,
    mutate_allowlist,
    permission_became_dangerous,
)
from cogs.core.audit import find_unique_audit_actor
from cogs.core.authz import DangerousActionRequest, authorize_dangerous_action
from cogs.core.lockdown import activate_lockdown, deactivate_lockdown, is_lockdown_active
from cogs.core.permissions import is_owner_id
from cogs.core.responses import response_engine
from cogs.logger import add_log, current_time
from cogs.module_registry import get_module_state, set_module_state
from cogs.server_config import get_channel_id, get_guild_config, is_admin, update_guild_config
from cogs.trigger_parser import parse_shorekeeper_trigger


BOT_ADD_AUDIT_WINDOW_SECONDS = 120
MASS_AUDIT_WINDOW_SECONDS = 30
AUDIT_ACTIONS = {
    "ban": discord.AuditLogAction.ban,
    "kick": discord.AuditLogAction.kick,
    "channel_delete": discord.AuditLogAction.channel_delete,
    "channel_create": discord.AuditLogAction.channel_create,
    "role_delete": discord.AuditLogAction.role_delete,
    "role_create": discord.AuditLogAction.role_create,
    "webhook": discord.AuditLogAction.webhook_create,
    "guild_update": discord.AuditLogAction.guild_update,
    "role_update": discord.AuditLogAction.role_update,
}


class AntiNuke(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.rate_tracker = RateTracker()

    def _config(self, guild) -> dict:
        return get_guild_config(guild.id)

    def _enabled_for_guild(self, guild) -> bool:
        config = self._config(guild)
        if not config.get("enabled"):
            return False
        if get_module_state(config, "anti_nuke") == "disabled":
            return False
        return bool((config.get("anti_nuke") or {}).get("enabled", False))

    def _bot_member(self, guild: discord.Guild):
        return guild.me or guild.get_member(self.bot.user.id)

    def _can_configure(self, member) -> bool:
        return is_owner_id(getattr(member, "id", None)) or is_admin(member)

    async def _find_bot_add_actor(self, guild: discord.Guild, added_bot: discord.Member):
        attribution = await find_unique_audit_actor(
            guild,
            discord.AuditLogAction.bot_add,
            target_id=added_bot.id,
            window_seconds=BOT_ADD_AUDIT_WINDOW_SECONDS,
        )
        return attribution.actor, attribution.reason

    async def _send_alert(self, guild: discord.Guild, title: str, description: str):
        channel_id = get_channel_id(guild.id, "mod_logs") or get_channel_id(guild.id, "logging")
        channel = guild.get_channel(channel_id) if channel_id else None
        if channel:
            await channel.send(embed=response_engine.anti_nuke_alert(title, description))

    async def _log(self, guild, payload: dict):
        add_log(guild.id, {"time": current_time(), **payload})

    def _lockdown_channels(self, guild: discord.Guild, config: dict):
        configured = [int(channel_id) for channel_id in (config.get("lockdown") or {}).get("channel_ids") or [] if channel_id]
        if configured:
            return [channel for channel_id in configured if (channel := guild.get_channel(channel_id))]
        owner_full = bool((config.get("lockdown") or {}).get("full_channels"))
        if owner_full:
            return [channel for channel in guild.channels if isinstance(channel, discord.abc.GuildChannel)]
        sensitive = []
        for key in ("mod_logs", "logging", "dashboard"):
            channel_id = get_channel_id(guild.id, key)
            channel = guild.get_channel(channel_id) if channel_id else None
            if channel:
                sensitive.append(channel)
        return sensitive or [channel for channel in guild.text_channels[:12]]

    def _authorize_enforcement(self, guild, target, action: str, required_permissions):
        bot_member = self._bot_member(guild)
        return authorize_dangerous_action(
            DangerousActionRequest(
                guild_config=self._config(guild),
                module="anti_nuke",
                actor=bot_member,
                bot_member=bot_member,
                target_member=target,
                target_role=None,
                actor_authorized=True,
                required_bot_permissions=required_permissions,
                required_actor_permissions=(),
                security_policy_allowed=True,
                security_action=action,
            )
        )

    async def apply_lockdown(self, guild: discord.Guild, actor, *, notify: bool = True):
        config = self._config(guild)
        bot_member = self._bot_member(guild)
        saved = {}
        for channel in self._lockdown_channels(guild, config):
            if not bot_member or not channel.permissions_for(bot_member).manage_channels:
                continue
            overwrite = channel.overwrites_for(guild.default_role)
            saved[str(channel.id)] = {
                "send_messages": overwrite.send_messages,
                "add_reactions": overwrite.add_reactions,
                "create_public_threads": overwrite.create_public_threads,
            }
            overwrite.send_messages = False
            overwrite.add_reactions = False
            try:
                await channel.set_permissions(
                    guild.default_role,
                    overwrite=overwrite,
                    reason="Shorekeeper emergency lockdown",
                )
                if bot_member:
                    bot_overwrite = channel.overwrites_for(bot_member)
                    bot_overwrite.send_messages = True
                    bot_overwrite.view_channel = True
                    await channel.set_permissions(
                        bot_member,
                        overwrite=bot_overwrite,
                        reason="Shorekeeper lockdown self-access",
                    )
            except (discord.Forbidden, discord.HTTPException):
                continue

        def updater(guild_config):
            activate_lockdown(guild_config, getattr(actor, "id", 0))
            guild_config.setdefault("lockdown", {})["saved_overwrites"] = saved

        update_guild_config(guild.id, updater)
        if notify:
            await self._send_alert(
                guild,
                "Emergency Lockdown",
                f"Lockdown was activated by {getattr(actor, 'mention', actor)}. Shorekeeper kept its own voice.",
            )

    async def release_lockdown(self, guild: discord.Guild, actor, *, notify: bool = True):
        config = self._config(guild)
        saved = ((config.get("lockdown") or {}).get("saved_overwrites") or {})
        bot_member = self._bot_member(guild)
        for channel_id, perms in saved.items():
            channel = guild.get_channel(int(channel_id))
            if not channel or not bot_member or not channel.permissions_for(bot_member).manage_channels:
                continue
            overwrite = channel.overwrites_for(guild.default_role)
            overwrite.send_messages = perms.get("send_messages")
            overwrite.add_reactions = perms.get("add_reactions")
            try:
                await channel.set_permissions(guild.default_role, overwrite=overwrite, reason="Shorekeeper lockdown release")
            except (discord.Forbidden, discord.HTTPException):
                continue

        def updater(guild_config):
            deactivate_lockdown(guild_config)

        update_guild_config(guild.id, updater)
        if notify:
            await self._send_alert(guild, "Lockdown Lifted", f"{getattr(actor, 'mention', actor)} restored the shore.")

    async def _maybe_lockdown(self, guild, actor, should_trigger: bool):
        if not should_trigger or is_lockdown_active(self._config(guild)):
            return
        await self.apply_lockdown(guild, actor or guild.me)

    async def _handle_mass_event(self, guild, action: str, target_id=None, extra=""):
        if not self._enabled_for_guild(guild):
            return
        config = self._config(guild)
        policy = config.get("anti_nuke") or {}
        bot_member = self._bot_member(guild)
        audit_action = AUDIT_ACTIONS.get(action)
        if audit_action:
            attribution = await find_unique_audit_actor(
                guild,
                audit_action,
                target_id=target_id,
                window_seconds=MASS_AUDIT_WINDOW_SECONDS,
            )
        else:
            attribution = type("Attr", (), {"actor": None, "reason": "audit_not_applicable"})()
        if actor_is_self(attribution.actor, bot_member):
            return
        if attribution.actor is not None and actor_is_allowlisted(attribution.actor, config):
            return
        decision = evaluate_mass_action(
            policy,
            self.rate_tracker,
            guild.id,
            action,
            actor=attribution.actor,
            guild_config=config,
        )
        if not decision.should_log:
            return
        actor_label = attribution.actor.mention if attribution.actor else "unknown"
        await self._log(
            guild,
            {
                "type": f"anti_nuke_{action}",
                "action": action,
                "count": decision.count,
                "reason": decision.reason,
                "attribution": attribution.reason,
                "actor_id": getattr(attribution.actor, "id", None),
                "target_id": target_id,
                "extra": extra,
            },
        )
        await self._send_alert(
            guild,
            f"Anti-Nuke {action.replace('_', ' ').title()}",
            f"Threshold watch: `{decision.count}` events. Attribution: `{attribution.reason}` ({actor_label}). Mode: `{decision.reason}`. {extra}".strip(),
        )
        if decision.trigger_lockdown:
            await self._maybe_lockdown(guild, attribution.actor, True)

    async def _remove_added_bot(self, member: discord.Member):
        decision = self._authorize_enforcement(member.guild, member, "anti_nuke_remove_bot", ("kick_members",))
        if not decision.allowed:
            return
        await member.kick(reason="Shorekeeper Anti-Nuke: unauthorized bot addition")

    async def _punish_actor(self, guild: discord.Guild, actor: discord.Member, punishment: str):
        reason = "Shorekeeper Anti-Nuke: unauthorized bot addition"
        if punishment == "ban":
            decision = self._authorize_enforcement(guild, actor, "anti_nuke_punish_actor", ("ban_members",))
            if not decision.allowed:
                return
            await guild.ban(actor, reason=reason)
        elif punishment == "kick":
            decision = self._authorize_enforcement(guild, actor, "anti_nuke_punish_actor", ("kick_members",))
            if not decision.allowed:
                return
            await actor.kick(reason=reason)
        elif punishment == "seal":
            seal_cog = self.bot.get_cog("Seal")
            if seal_cog is None:
                # If the Seal cog is not loaded, we fall back to kick?
                # But we should log an error and maybe default to kick.
                # For now, let's fallback to kick and log.
                print("Seal cog not found, falling back to kick for anti-nuke punishment")
                await self._punish_actor(guild, actor, "kick")  # recursive call, but we must avoid infinite loop.
                return
            success, detail = await seal_cog.seal_member(actor)
            if success:
                await self._send_alert(guild, "Anti-Nuke: Seal Actor", f"{actor.mention} has been sealed. {detail}")
            else:
                await self._send_alert(guild, "Anti-Nuke: Seal Failed", f"Failed to seal {actor.mention}: {detail}")
                # Then we might want to fallback to kick?
                await self._punish_actor(guild, actor, "kick")

    async def _handle_mass_join(self, guild: discord.Guild, member):
        """Monitor join velocity (raid_join) without punishing anyone.

        Threshold breaches are logged and alerted; lockdown still requires the
        guild policy to opt in via `trigger_lockdown_on_mass_action`.
        """
        if not self._enabled_for_guild(guild):
            return
        config = self._config(guild)
        policy = config.get("anti_nuke") or {}
        decision = evaluate_mass_action(
            policy,
            self.rate_tracker,
            guild.id,
            "raid_join",
            actor=None,
            guild_config=config,
        )
        if not decision.should_log:
            return
        await self._log(
            guild,
            {
                "type": "anti_nuke_raid_join",
                "action": "raid_join",
                "count": decision.count,
                "reason": decision.reason,
                "member_id": getattr(member, "id", None),
            },
        )
        await self._send_alert(
            guild,
            "Anti-Nuke Raid Watch",
            f"`{decision.count}` members joined inside the watch window. Mode: `{decision.reason}`. No member was punished.",
        )
        if decision.trigger_lockdown:
            await self._maybe_lockdown(guild, guild.me, True)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if not getattr(member, "bot", False):
            await self._handle_mass_join(member.guild, member)
            return
        await self._handle_bot_join(member)

    async def _handle_bot_join(self, member: discord.Member):
        if not self._enabled_for_guild(member.guild):
            return
        config = self._config(member.guild)
        actor, attribution = await self._find_bot_add_actor(member.guild, member)
        bot_member = self._bot_member(member.guild)
        decision = evaluate_bot_addition(member, actor, bot_member, config)
        await self._log(
            member.guild,
            {
                "type": "anti_nuke_bot_add",
                "added_bot": str(member),
                "added_bot_id": member.id,
                "actor": str(actor) if actor else None,
                "actor_id": getattr(actor, "id", None),
                "attribution": attribution,
                "decision": decision.reason,
                "removed_added_bot": decision.remove_added_bot,
                "punished_actor": decision.punish_actor,
                "punishment": decision.punishment,
                "lockdown_triggered": decision.trigger_lockdown,
            },
        )
        if decision.reason.startswith("audit_attribution_") or decision.reason == "audit_actor_not_member":
            await self._send_alert(
                member.guild,
                "Anti-Nuke Bot Addition",
                f"A bot arrived ({member.mention}), but the hand that invited it is unclear. No human was punished.",
            )
            return
        if not decision.remove_added_bot and not decision.punish_actor:
            if decision.should_log:
                await self._send_alert(
                    member.guild,
                    "Anti-Nuke Bot Addition",
                    f"Bot addition noted for {member.mention}. Mode: `{decision.reason}`.",
                )
            return
        errors = []
        try:
            if decision.remove_added_bot:
                await self._remove_added_bot(member)
        except Exception:
            errors.append("remove bot failed")
            traceback.print_exc()
        try:
            if decision.punish_actor and actor:
                await self._punish_actor(member.guild, actor, decision.punishment or "kick")
        except Exception:
            errors.append("punish actor failed")
            traceback.print_exc()
        detail = (
            f"Unauthorized bot {member.mention} was handled. "
            f"Actor: {actor.mention if actor else 'unknown'}. "
            f"Punishment: `{decision.punishment or 'none'}`."
        )
        if decision.trigger_lockdown:
            await self._maybe_lockdown(member.guild, actor, True)
            detail += " Emergency lockdown was requested."
        if errors:
            detail += " " + " ".join(errors)
        await self._send_alert(member.guild, "Anti-Nuke Bot Addition", detail)

    @commands.Cog.listener()
    async def on_member_ban(self, guild, user):
        await self._handle_mass_event(guild, "ban", getattr(user, "id", None))

    @commands.Cog.listener()
    async def on_member_remove(self, member):
        if not getattr(member, "guild", None):
            return
        if not self._enabled_for_guild(member.guild):
            return
        attribution = await find_unique_audit_actor(
            member.guild,
            discord.AuditLogAction.kick,
            target_id=member.id,
            window_seconds=MASS_AUDIT_WINDOW_SECONDS,
        )
        if attribution.reason != "audit_attribution_identified":
            return
        await self._handle_mass_event(member.guild, "kick", member.id)

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel):
        await self._handle_mass_event(channel.guild, "channel_create", channel.id)

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel):
        await self._handle_mass_event(channel.guild, "channel_delete", channel.id)

    @commands.Cog.listener()
    async def on_guild_role_create(self, role):
        await self._handle_mass_event(role.guild, "role_create", role.id)

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role):
        await self._handle_mass_event(role.guild, "role_delete", role.id)

    @commands.Cog.listener()
    async def on_guild_role_update(self, before, after):
        if permission_became_dangerous(before.permissions, after.permissions):
            await self._handle_mass_event(after.guild, "role_update", after.id, extra="dangerous permission granted")

    @commands.Cog.listener()
    async def on_guild_update(self, before, after):
        if not guild_update_is_dangerous(before, after):
            return
        await self._handle_mass_event(after, "guild_update", after.id)

    @commands.Cog.listener()
    async def on_webhooks_update(self, channel):
        await self._handle_mass_event(channel.guild, "webhook", channel.id)

    async def _status_embed(self, config: dict):
        return response_engine.anti_nuke_alert("Anti-Nuke Status", format_anti_nuke_status(config))

    def _parse_entity_id(self, trigger, args, kind: str):
        if kind == "role":
            if trigger.get("role_id"):
                return int(trigger["role_id"])
        if kind in {"user", "bot"} and trigger.get("target_id"):
            return int(trigger["target_id"])
        for token in args:
            if str(token).isdigit():
                return int(token)
        return None

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        trigger = parse_shorekeeper_trigger(self.bot, message)
        if not trigger or trigger.get("keyword") != "antinuke":
            return
        if not self._can_configure(message.author):
            return await message.channel.send(embed=response_engine.permission_denied("You cannot change Anti-Nuke."))
        config = self._config(message.guild)
        args = [str(token).lower() for token in trigger.get("args") or []]
        # Allow status/check commands to work even when module is disabled
        if not args or args[0] in {"status", "show"}:
            return await message.channel.send(embed=await self._status_embed(config))

        action = args[0]
        if action in {"enable", "on"}:
            mode = args[1] if len(args) > 1 and args[1] in {"monitor", "enforcement"} else None

            def updater(guild_config):
                policy = guild_config.setdefault("anti_nuke", {})
                policy["enabled"] = True
                if mode:
                    policy["mode"] = mode
                set_module_state(guild_config, "anti_nuke", "active")

            update_guild_config(message.guild.id, updater)
            refreshed = self._config(message.guild)
            from cogs.core.anti_nuke import anti_nuke_status_label

            return await message.channel.send(
                embed=response_engine.configuration(
                    "Anti-Nuke Armed",
                    f"Watchfulness is armed. Status: **{anti_nuke_status_label(refreshed.get('anti_nuke') or {})}**.",
                )
            )
        if action in {"disable", "off"}:

            def updater(guild_config):
                guild_config.setdefault("anti_nuke", {})["enabled"] = False

            update_guild_config(message.guild.id, updater)
            return await message.channel.send(embed=response_engine.configuration("Anti-Nuke", "Anti-Nuke is now **DISABLED**."))
        if action == "mode":
            if len(args) < 2 or args[1] not in {"monitor", "enforcement", "disabled"}:
                return await message.channel.send(
                    embed=response_engine.parser_error("Use `antinuke mode monitor` or `antinuke mode enforcement`.")
                )
            requested = args[1]

            def updater(guild_config):
                policy = guild_config.setdefault("anti_nuke", {})
                if requested == "disabled":
                    policy["enabled"] = False
                    return
                policy["enabled"] = True
                policy["mode"] = requested
                set_module_state(guild_config, "anti_nuke", "active")

            update_guild_config(message.guild.id, updater)
            label = "DISABLED" if requested == "disabled" else requested.upper()
            return await message.channel.send(embed=response_engine.configuration("Anti-Nuke Mode", f"Anti-Nuke is now **{label}**."))
        if action in {"whitelist", "allowlist", "trust", "untrust"}:
            return await self._whitelist_command(message, trigger, args)
        if action == "threshold":
            if len(args) < 3 or args[1] not in DEFAULT_THRESHOLDS or not args[2].isdigit():
                keys = ", ".join(DEFAULT_THRESHOLDS)
                return await message.channel.send(
                    embed=response_engine.parser_error(f"Use `antinuke threshold <{keys}> <number>`.")
                )

            def updater(guild_config):
                thresholds = guild_config.setdefault("anti_nuke", {}).setdefault("thresholds", {})
                thresholds[args[1]] = max(1, int(args[2]))

            update_guild_config(message.guild.id, updater)
            return await message.channel.send(
                embed=response_engine.configuration("Anti-Nuke Threshold", f"`{args[1]}` now trips at `{max(1, int(args[2]))}`.")
            )
        if action in {"cooldown", "window"}:
            if len(args) < 2 or not args[1].isdigit():
                return await message.channel.send(embed=response_engine.parser_error(f"Use `antinuke {action} <seconds>`."))
            key = "cooldown_seconds" if action == "cooldown" else "window_seconds"

            def updater(guild_config):
                guild_config.setdefault("anti_nuke", {})[key] = max(1, int(args[1]))

            update_guild_config(message.guild.id, updater)
            return await message.channel.send(
                embed=response_engine.configuration("Anti-Nuke Timing", f"`{key}` is now `{max(1, int(args[1]))}` seconds.")
            )
        if action == "punishment":
            if len(args) < 2 or args[1] not in {"kick", "ban", "none", "seal"}:
                return await message.channel.send(embed=response_engine.parser_error("Use `antinuke punishment kick|ban|none|seal`."))

            def updater(guild_config):
                guild_config.setdefault("anti_nuke", {})["bot_add_punishment"] = args[1]

            update_guild_config(message.guild.id, updater)
            return await message.channel.send(
                embed=response_engine.configuration("Anti-Nuke Punishment", f"Unauthorized bot-add punishment is `{args[1]}`.")
            )
        if action == "lockdown":
            if len(args) < 3 or args[1] not in {"bot", "mass"} or args[2] not in {"on", "off"}:
                return await message.channel.send(
                    embed=response_engine.parser_error("Use `antinuke lockdown bot on|off` or `antinuke lockdown mass on|off`.")
                )
            key = "trigger_lockdown_on_bot_add" if args[1] == "bot" else "trigger_lockdown_on_mass_action"

            def updater(guild_config):
                guild_config.setdefault("anti_nuke", {})[key] = args[2] == "on"

            update_guild_config(message.guild.id, updater)
            return await message.channel.send(
                embed=response_engine.configuration("Anti-Nuke Lockdown", f"`{key}` is now `{args[2] == 'on'}`.")
            )
        return await message.channel.send(
            embed=response_engine.parser_error(
                "Anti-Nuke commands: status, enable, disable, mode, whitelist, threshold, cooldown, window, punishment, lockdown."
            )
        )

    async def _whitelist_command(self, message, trigger, args):
        config = self._config(message.guild)
        if args[0] in {"whitelist", "allowlist"} and (len(args) == 1 or args[1] in {"list", "status"}):
            return await message.channel.send(embed=response_engine.configuration("Anti-Nuke Allowlist", format_allowlist(config)))
        verb = args[0]
        rest = args[1:]
        if verb in {"whitelist", "allowlist"} and rest:
            verb = rest[0]
            rest = rest[1:]
        if verb == "trust":
            verb = "add"
        if verb == "untrust":
            verb = "remove"
        if verb not in {"add", "remove"} or not rest or rest[0] not in {"bot", "user", "role"}:
            return await message.channel.send(
                embed=response_engine.parser_error(
                    "Use `antinuke whitelist add bot|user|role <id>` or `antinuke whitelist remove bot|user|role <id>`."
                )
            )
        kind = rest[0]
        entity_id = self._parse_entity_id(trigger, rest[1:], kind)
        if not entity_id:
            return await message.channel.send(embed=response_engine.parser_error("Provide a Discord ID or mention for the allowlist entry."))

        def updater(guild_config):
            mutate_allowlist(guild_config.setdefault("anti_nuke", {}), kind, verb, entity_id)

        update_guild_config(message.guild.id, updater)
        refreshed = self._config(message.guild)
        return await message.channel.send(
            embed=response_engine.configuration(
                "Anti-Nuke Allowlist Updated",
                f"{verb.title()}ed {kind} `{entity_id}`.\n\n{format_allowlist(refreshed)}",
            )
        )


async def setup(bot):
    await bot.add_cog(AntiNuke(bot))
