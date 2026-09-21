import os
import platform

import discord
from discord import app_commands
from discord.ext import commands

from cogs.core.anti_nuke import format_anti_nuke_status
from cogs.core.lockdown import activate_lockdown, deactivate_lockdown, is_lockdown_active, lockdown_state
from cogs.core.parser import INACTIVE_KEYWORD
from cogs.core.permissions import is_owner_id as is_sole_owner
from cogs.core.responses import response_engine
from cogs.module_registry import (
    MODULES,
    get_module_state,
    is_retired_module,
    mention_command_list,
    module_names,
    normalize_module_name,
    set_module_state,
)
from cogs.server_config import get_guild_config, update_guild_config
from cogs.trigger_parser import parse_shorekeeper_trigger


def _ram_mb():
    try:
        if os.name == "nt":
            import ctypes
            import ctypes.wintypes

            class ProcessMemoryCounters(ctypes.Structure):
                _fields_ = [
                    ("cb", ctypes.wintypes.DWORD),
                    ("PageFaultCount", ctypes.wintypes.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t),
                    ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedUsage", ctypes.c_size_t),
                    ("QuotaPagedUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedUsage", ctypes.c_size_t),
                    ("QuotaNonPagedUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t),
                    ("PeakPagefileUsage", ctypes.c_size_t),
                ]

            counters = ProcessMemoryCounters()
            counters.cb = ctypes.sizeof(counters)
            ctypes.windll.kernel32.GetCurrentProcess.restype = ctypes.wintypes.HANDLE
            handle = ctypes.windll.kernel32.GetCurrentProcess()
            try:
                getter = ctypes.windll.kernel32.K32GetProcessMemoryInfo
            except AttributeError:
                getter = ctypes.windll.psapi.GetProcessMemoryInfo
            getter.argtypes = [
                ctypes.wintypes.HANDLE,
                ctypes.POINTER(ProcessMemoryCounters),
                ctypes.wintypes.DWORD,
            ]
            getter.restype = ctypes.wintypes.BOOL
            ok = getter(handle, ctypes.byref(counters), counters.cb)
            return round(counters.WorkingSetSize / (1024 * 1024), 1) if ok else "unknown"
        import resource

        usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return round(usage / 1024, 1)
    except Exception:
        return "unknown"


def toggle_anti_nuke(config: dict, enabled: bool) -> None:
    """Enable or disable the anti-nuke engine for a guild (pure mutation helper)."""
    policy = config.setdefault("anti_nuke", {})
    if not isinstance(policy, dict):
        policy = {}
        config["anti_nuke"] = policy
    policy["enabled"] = bool(enabled)


def set_anti_nuke_mode(config: dict, mode: str) -> None:
    """Set the anti-nuke mode to ``monitor`` or ``enforcement``."""
    policy = config.setdefault("anti_nuke", {})
    if not isinstance(policy, dict):
        policy = {}
        config["anti_nuke"] = policy
    normalized = (mode or "").lower()
    if normalized in {"monitor", "enforcement"}:
        policy["mode"] = normalized


class ModuleManager(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def _can_manage_owner_settings(self, user, guild):
        if not guild or not user:
            return False
        return is_sole_owner(user.id)

    async def _can_manage_modules(self, user, guild):
        if await self._can_manage_owner_settings(user, guild):
            return True
        if not guild:
            return False
        cfg = get_guild_config(guild.id)
        admin_ids = {int(value) for value in cfg.get("admin_ids", []) if str(value).isdigit() or isinstance(value, int)}
        return getattr(user, "id", None) in admin_ids

    def _module_lines(self, guild):
        cfg = get_guild_config(guild.id)
        lines = []
        for module in self._active_module_names(cfg):
            state = get_module_state(cfg, module)
            lines.append(f"`{module}`: **ACTIVE** (loaded) - {state}")
        for module in self._configured_missing_modules(cfg):
            state = get_module_state(cfg, module)
            lines.append(f"`{module}`: **configured_missing** (not loaded) - {state}")
        if not lines:
            lines.append("No modules are configured for this guild.")
        return lines

    def _configured_missing_modules(self, guild_config):
        """Modules that are configured on but whose extensions never loaded."""
        missing = []
        for module in module_names():
            if is_retired_module(module):
                continue
            if get_module_state(guild_config, module) == "disabled":
                continue
            if not self._module_loaded(module):
                missing.append(module)
        return missing

    def _active_module_names(self, guild_config):
        return [
            module
            for module in module_names()
            if get_module_state(guild_config, module) != "disabled"
            and self._module_loaded(module)
        ]

    def _module_loaded(self, module):
        meta = MODULES.get(module, {})
        extensions = meta.get("extensions") or [meta.get("extension")]
        return all(ext in self.bot.extensions for ext in extensions if ext)

    async def _set_module(self, interaction, module, state):
        if not interaction.guild:
            embed = response_engine.failure(
                title="Invalid Context",
                description="This command must be used in a server."
            )
            return await interaction.response.send_message(embed=embed, ephemeral=True)
        if not await self._can_manage_modules(interaction.user, interaction.guild):
            embed = response_engine.permission_denied(
                detail="You lack the necessary permissions to manage modules."
            )
            return await interaction.response.send_message(embed=embed, ephemeral=True)

        module = normalize_module_name(module)
        if module == "core" or module not in MODULES:
            embed = response_engine.failure(
                title="Unknown Module",
                description=f"Unknown module. Available: `{', '.join(module_names())}`"
            )
            return await interaction.response.send_message(embed=embed, ephemeral=True)

        def updater(config):
            set_module_state(config, module, state)

        update_guild_config(interaction.guild.id, updater)
        await interaction.response.defer(ephemeral=True, thinking=True)
        syncer = getattr(self.bot, "sync_visible_commands", None)
        if syncer:
            await syncer(interaction.guild)
        embed = response_engine.configuration(
            f"Module {state.upper()}",
            f"`{module}` is now **{state.upper()}**.\nSlash commands were synced for this server."
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="enablecommands", description="Enable and show a module's slash commands.")
    async def enablecommands(self, interaction: discord.Interaction, module: str):
        await self._set_module(interaction, module, "active")

    @app_commands.command(name="disablecommands", description="Hide a module's slash commands while keeping mention commands.")
    async def disablecommands(self, interaction: discord.Interaction, module: str):
        await self._set_module(interaction, module, "hidden")

    @app_commands.command(name="addserveradmin", description="Allow a user to use server admin commands.")
    async def addserveradmin(self, interaction: discord.Interaction, user: discord.Member):
        if not interaction.guild:
            embed = response_engine.failure(
                title="Invalid Context",
                description="This command must be used in a server."
            )
            return await interaction.response.send_message(embed=embed, ephemeral=True)
        if not await self._can_manage_owner_settings(interaction.user, interaction.guild):
            embed = response_engine.permission_denied(
                detail="You lack the necessary permissions to add server administrators."
            )
            return await interaction.response.send_message(embed=embed, ephemeral=True)

        def updater(config):
            admins = config.setdefault("admin_ids", [])
            if user.id not in admins:
                admins.append(user.id)

        update_guild_config(interaction.guild.id, updater)
        embed = response_engine.success(
            "Server Admin Added",
            f"{user.mention} can now use server admin commands."
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="removeserveradmin", description="Remove a user's server admin command access.")
    async def removeserveradmin(self, interaction: discord.Interaction, user: discord.Member):
        if not interaction.guild:
            embed = response_engine.failure(
                title="Invalid Context",
                description="This command must be used in a server."
            )
            return await interaction.response.send_message(embed=embed, ephemeral=True)
        if not await self._can_manage_owner_settings(interaction.user, interaction.guild):
            embed = response_engine.permission_denied(
                detail="You lack the necessary permissions to remove server administrators."
            )
            return await interaction.response.send_message(embed=embed, ephemeral=True)

        def updater(config):
            admins = config.setdefault("admin_ids", [])
            if user.id in admins:
                admins.remove(user.id)

        update_guild_config(interaction.guild.id, updater)
        embed = response_engine.success(
            "Server Admin Removed",
            f"{user.mention} can no longer use server admin commands."
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="serveradmins", description="List users with server admin command access.")
    async def serveradmins(self, interaction: discord.Interaction):
        if not interaction.guild:
            embed = response_engine.failure(
                title="Invalid Context",
                description="This command must be used in a server."
            )
            return await interaction.response.send_message(embed=embed, ephemeral=True)
        if not await self._can_manage_owner_settings(interaction.user, interaction.guild):
            embed = response_engine.permission_denied(
                detail="You lack the necessary permissions to view server administrators."
            )
            return await interaction.response.send_message(embed=embed, ephemeral=True)

        cfg = get_guild_config(interaction.guild.id)
        admin_ids = sorted(set(cfg.get("admin_ids", [])))
        lines = [f"- <@{user_id}> (`{user_id}`)" for user_id in admin_ids]
        embed = response_engine.build(
            title="Server Admins",
            description="\n".join(lines) if lines else "No server admins configured.",
            color=0x5865F2
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="antinukeenable", description="Enable Anti-Nuke protection for this server.")
    async def antinukeenable(self, interaction: discord.Interaction):
        if not interaction.guild:
            embed = response_engine.failure(
                title="Invalid Context",
                description="This command must be used in a server."
            )
            return await interaction.response.send_message(embed=embed, ephemeral=True)
        if not await self._can_manage_owner_settings(interaction.user, interaction.guild):
            embed = response_engine.permission_denied(
                detail="You lack the necessary permissions to enable Anti-Nuke protection."
            )
            return await interaction.response.send_message(embed=embed, ephemeral=True)
        update_guild_config(interaction.guild.id, lambda config: toggle_anti_nuke(config, True))
        embed = response_engine.success(
            "Anti-Nuke Enabled",
            "Anti-Nuke protection is now **enabled**. View it via `/settings`."
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="antinukedisable", description="Disable Anti-Nuke protection for this server.")
    async def antinukedisable(self, interaction: discord.Interaction):
        if not interaction.guild:
            embed = response_engine.failure(
                title="Invalid Context",
                description="This command must be used in a server."
            )
            return await interaction.response.send_message(embed=embed, ephemeral=True)
        if not await self._can_manage_owner_settings(interaction.user, interaction.guild):
            embed = response_engine.permission_denied(
                detail="You lack the necessary permissions to disable Anti-Nuke protection."
            )
            return await interaction.response.send_message(embed=embed, ephemeral=True)
        update_guild_config(interaction.guild.id, lambda config: toggle_anti_nuke(config, False))
        embed = response_engine.success(
            "Anti-Nuke Disabled",
            "Anti-Nuke protection is now **disabled**."
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="antinukemode", description="Set Anti-Nuke mode: monitor (log only) or enforcement (act).")
    async def antinukemode(self, interaction: discord.Interaction, mode: str):
        if not interaction.guild:
            embed = response_engine.failure(
                title="Invalid Context",
                description="This command must be used in a server."
            )
            return await interaction.response.send_message(embed=embed, ephemeral=True)
        if not await self._can_manage_owner_settings(interaction.user, interaction.guild):
            embed = response_engine.permission_denied(
                detail="You lack the necessary permissions to change Anti-Nuke mode."
            )
            return await interaction.response.send_message(embed=embed, ephemeral=True)
        normalized = (mode or "").lower()
        if normalized not in {"monitor", "enforcement"}:
            embed = response_engine.failure(
                title="Invalid Mode",
                description="Mode must be `monitor` or `enforcement`."
            )
            return await interaction.response.send_message(embed=embed, ephemeral=True)
        update_guild_config(interaction.guild.id, lambda config: set_anti_nuke_mode(config, normalized))
        embed = response_engine.configuration(
            "Anti-Nuke Mode",
            f"Anti-Nuke mode is now `{normalized}`."
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="status", description="Show Shorekeeper module status.")
    async def status(self, interaction: discord.Interaction):
        if not interaction.guild:
            embed = response_engine.failure(
                title="Invalid Context",
                description="This command must be used in a server."
            )
            return await interaction.response.send_message(embed=embed, ephemeral=True)
        embed = response_engine.build(
            title="Shorekeeper Status",
            description="\n".join(self._module_lines(interaction.guild)),
            color=0x5865F2
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="settings", description="Show server configuration summary.")
    async def settings(self, interaction: discord.Interaction):
        if not interaction.guild:
            embed = response_engine.failure(
                title="Invalid Context",
                description="This command must be used in a server."
            )
            return await interaction.response.send_message(embed=embed, ephemeral=True)
        if not await self._can_manage_owner_settings(interaction.user, interaction.guild):
            embed = response_engine.permission_denied(
                detail="You lack the necessary permissions to view server settings."
            )
            return await interaction.response.send_message(embed=embed, ephemeral=True)

        cfg = get_guild_config(interaction.guild.id)
        embed = response_engine.build(
            title="Server Settings",
            description="",
            color=0x2ECC71
        )
        embed.add_field(name="Modules", value="\n".join(self._module_lines(interaction.guild))[:1024], inline=False)
        embed.add_field(name="Channels", value=str(cfg.get("channels", {}))[:1024], inline=False)
        immunity_role_id = cfg.get("immunity_role")
        immunity_role = interaction.guild.get_role(immunity_role_id) if immunity_role_id else None
        embed.add_field(
            name="Protection",
            value=f"Immunity Role: {immunity_role.mention if immunity_role else immunity_role_id or 'Not set'}",
            inline=False,
        )
        embed.add_field(name="Anti-Nuke", value=format_anti_nuke_status(cfg)[:1024], inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="help", description="Show Shorekeeper handoff commands.")
    async def help(self, interaction: discord.Interaction):
        cfg = get_guild_config(interaction.guild.id) if interaction.guild else {"modules": {}}
        embed = response_engine.build(
            title="Shorekeeper Commands",
            description=(
                "Mention commands use `@Shorekeeper command ...`.\n"
                "Use `@Shorekeeper shorehelp` for the same command list in chat."
            ),
            color=0x5865F2
        )
        for module in self._active_module_names(cfg):
            meta = MODULES[module]
            slash = ", ".join(f"`/{name}`" for name in meta.get("slash", [])) or "None"
            mention = mention_command_list(meta.get("mention", []))
            embed.add_field(
                name=module.title(),
                value=f"Slash: {slash}\nMention: {mention}"[:1024],
                inline=False,
            )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        trigger = parse_shorekeeper_trigger(self.bot, message)
        if not trigger:
            return

        keyword = trigger["keyword"]
        if keyword == INACTIVE_KEYWORD:
            return await message.channel.send(
                embed=response_engine.permission_denied(
                    "This guild is not activated. Shorekeeper remains still until the sole owner enables it."
                )
            )
        if keyword == "health":
            return await self._health(message)
        if keyword == "update":
            return await self._update(message)
        if keyword == "resync":
            return await self._resync(message)
        if keyword == "module":
            return await self._module_command(message, trigger)
        if keyword == "guild":
            return await self._guild_command(message, trigger)
        if keyword in {"activateguild", "deactivateguild", "guildstatus"}:
            return await self._guild_alias_command(message, keyword)
        if keyword == "lockdown":
            return await self._lockdown_command(message, trigger)

    async def _health(self, message):
        cfg = get_guild_config(message.guild.id)
        missing_channels = []
        for key, channel_id in cfg.get("channels", {}).items():
            if channel_id and not message.guild.get_channel(channel_id):
                missing_channels.append(f"{key}:{channel_id}")

        broken_webhooks = []
        for channel in message.guild.text_channels:
            try:
                hooks = await channel.webhooks()
            except (discord.Forbidden, discord.HTTPException):
                continue
            for hook in hooks:
                if hook.channel_id != channel.id:
                    broken_webhooks.append(f"{channel.name}/{hook.name}")

        embed = response_engine.build(
            title="Health Check",
            description="",
            color=0x57F287 if not missing_channels else 0xFEE75C
        )
        embed.add_field(name="Loaded Cogs", value=str(len(self.bot.cogs)), inline=True)
        embed.add_field(name="Extensions", value=str(len(self.bot.extensions)), inline=True)
        embed.add_field(name="RAM", value=f"{_ram_mb()} MB", inline=True)
        embed.add_field(name="Python", value=platform.python_version(), inline=True)
        embed.add_field(name="Missing Channels", value="\n".join(missing_channels) or "None", inline=False)
        embed.add_field(name="Broken Webhooks", value="\n".join(broken_webhooks[:10]) or "None found", inline=False)
        await message.channel.send(embed=embed)

    async def _resync(self, message):
        if not await self._can_manage_modules(message.author, message.guild):
            embed = response_engine.failure(
                title="Insufficient Permissions",
                description="Only the server owner can resync slash commands."
            )
            return await message.channel.send(embed=embed)

        # Create initial embed for resync
        embed = response_engine.build(
            title="Resyncing Slash Commands",
            description="Clearing slash command tree...",
            color=0x5865F2
        )
        status = await message.channel.send(embed=embed)
        if hasattr(self.bot, "_restore_tree_commands"):
            self.bot._restore_tree_commands()
        if hasattr(self.bot, "remember_app_commands"):
            self.bot.remember_app_commands()

        # Update to rebuilding
        embed.description = "Rebuilding slash command tree..."
        await status.edit(embed=embed)
        synced_count = 0
        if hasattr(self.bot, "sync_visible_commands"):
            synced_count = await self.bot.sync_visible_commands(message.guild, reason="owner resync")

        health = getattr(self.bot, "slash_health", {})
        # Update to final
        embed.description = (
            "Slash commands resynced.\n"
            f"registered={health.get('registered', 0)} "
            f"visible={health.get('visible', 0)} "
            f"synced={synced_count}"
        )
        await status.edit(embed=embed)

    async def _module_command(self, message, trigger):
        if not await self._can_manage_modules(message.author, message.guild):
            embed = response_engine.failure(
                title="Insufficient Permissions",
                description="Only the server owner can manage modules."
            )
            return await message.channel.send(embed=embed)
        args = trigger["args"]
        if not args:
            embed = response_engine.info(
                title="Module Command Usage",
                description="Use `module debug <module>` or `module recover`."
            )
            return await message.channel.send(embed=embed)
        action = args[0].lower()
        if action in {"debug", "disable", "disabled", "hidden", "active", "enable", "enabled"}:
            module = normalize_module_name(args[1] if len(args) > 1 else "")
            if module not in MODULES or module == "core":
                embed = response_engine.failure(
                    title="Unknown Module",
                    description=f"Unknown module. Available: `{', '.join(module_names())}`"
                )
                return await message.channel.send(embed=embed)
            if is_retired_module(module):
                return await message.channel.send(embed=response_engine.warning("Module Retired", f"`{module}` was intentionally removed and cannot be enabled."))
            state = {
                "disable": "disabled",
                "disabled": "disabled",
                "hidden": "hidden",
                "active": "active",
                "enable": "active",
                "enabled": "active",
                "debug": "debug",
            }[action]

            def updater(config):
                set_module_state(config, module, state)

            update_guild_config(message.guild.id, updater)
            syncer = getattr(self.bot, "sync_visible_commands", None)
            if syncer:
                await syncer(message.guild)
            return await message.channel.send(embed=response_engine.configuration("Module Updated", f"`{module}` is now **{state}**."))

        if action == "recover":
            loaded = []
            failed = []
            for meta in MODULES.values():
                extensions = meta.get("extensions") or [meta.get("extension")]
                for extension in extensions:
                    if not extension or extension in self.bot.extensions:
                        continue
                    try:
                        await self.bot.load_extension(extension)
                        loaded.append(extension)
                    except Exception as exc:
                        failed.append(f"{extension}: {type(exc).__name__}: {exc}")
            if hasattr(self.bot, "remember_app_commands"):
                self.bot.remember_app_commands()
            if hasattr(self.bot, "sync_visible_commands"):
                await self.bot.sync_visible_commands(message.guild)
            embed = response_engine.build(
                title="Module Recovery Complete",
                description=(
                    f"Loaded: `{len(loaded)}`\n"
                    f"Failed: `{len(failed)}`" + (("\n" + "\n".join(failed[:5])) if failed else "")
                ),
                color=0x5865F2
            )
            return await message.channel.send(embed=embed)

        embed = response_engine.failure(
            title="Unknown Action",
            description="Unknown module action. Use `debug`, `disable`, `enable`, or `recover`."
        )
        return await message.channel.send(embed=embed)

    async def _guild_alias_command(self, message, keyword):
        """Owner-only activation aliases: activateguild / deactivateguild / guildstatus."""
        action = {
            "activateguild": "enable",
            "deactivateguild": "disable",
            "guildstatus": "status",
        }[keyword]
        return await self._guild_command(
            message,
            {"keyword": "guild", "main": f"guild {action}", "args": [action], "extra": ""},
        )

    async def _guild_command(self, message, trigger):
        if not await self._can_manage_owner_settings(message.author, message.guild):
            return await message.channel.send(embed=response_engine.permission_denied("Only the sole Shorekeeper owner can activate or silence a guild."))
        args = [token.lower() for token in (trigger.get("args") or [])]
        if not args or args[0] not in {"enable", "disable", "status"}:
            return await message.channel.send(
                embed=response_engine.parser_error(
                    "Use `@Shorekeeper guild enable`, `@Shorekeeper guild disable`, "
                    "`@Shorekeeper guild status`, `@Shorekeeper activateguild`, "
                    "`@Shorekeeper deactivateguild`, or `@Shorekeeper guildstatus`."
                )
            )

        action = args[0]
        if action == "status":
            cfg = get_guild_config(message.guild.id)
            state = "active" if cfg.get("enabled") else "silent"
            return await message.channel.send(embed=response_engine.configuration("Guild Status", f"This guild is **{state}**."))

        # Get current state to make enable/disable idempotent
        cfg = get_guild_config(message.guild.id)
        currently_enabled = cfg.get("enabled", False)

        if action == "enable":
            if currently_enabled:
                return await message.channel.send(embed=response_engine.configuration("Guild Status", f"This guild is already **active**."))
            detail = "Shorekeeper will watch this guild."
            title = "Guild Activated"
        elif action == "disable":
            if not currently_enabled:
                return await message.channel.send(embed=response_engine.configuration("Guild Status", f"This guild is already **silent**."))
            detail = "Shorekeeper will remain still here until activated again."
            title = "Guild Silenced"
        else:
            # Should not happen due to validation above, but just in case
            return await message.channel.send(embed=response_engine.parser_error("Invalid action"))

        def updater(config):
            config["enabled"] = action == "enable"

        update_guild_config(message.guild.id, updater)
        syncer = getattr(self.bot, "sync_visible_commands", None)
        if syncer:
            await syncer(message.guild)
        return await message.channel.send(embed=response_engine.configuration(title, detail))

    async def _lockdown_command(self, message, trigger):
        if not await self._can_manage_modules(message.author, message.guild):
            return await message.channel.send(embed=response_engine.permission_denied("You are not authorized to command emergency lockdown."))
        args = [token.lower() for token in (trigger.get("args") or [])]
        action = args[0] if args else "status"
        if action in {"on", "enable", "start"}:
            return await self._set_lockdown(message, True)
        if action in {"off", "disable", "end"}:
            return await self._set_lockdown(message, False)
        cfg = get_guild_config(message.guild.id)
        state = lockdown_state(cfg)
        status = "active" if state.get("enabled") else "clear"
        activated_by = f"<@{state.get('activated_by')}>" if state.get("activated_by") else "none"
        return await message.channel.send(
            embed=response_engine.lockdown(
                "Lockdown Status",
                f"State: **{status}**\nActivated by: {activated_by}\nRecorded at: `{state.get('activated_at') or 'n/a'}`",
            )
        )

    async def _set_lockdown(self, message, enabled: bool):
        saved = {}

        def updater(config):
            nonlocal saved
            if enabled:
                saved = activate_lockdown(config, message.author.id)
            else:
                saved = deactivate_lockdown(config)

        update_guild_config(message.guild.id, updater)
        anti_nuke = self.bot.get_cog("AntiNuke")
        if anti_nuke:
            if enabled:
                await anti_nuke.apply_lockdown(message.guild, message.author, notify=False)
            else:
                await anti_nuke.release_lockdown(message.guild, message.author, notify=False)
        title = "Emergency Lockdown" if enabled else "Lockdown Lifted"
        detail = (
            "Dangerous motion is being constrained. Shorekeeper can still speak where required."
            if enabled
            else "The shore is open again. Watchfulness remains."
        )
        return await message.channel.send(embed=response_engine.lockdown(title, detail))

    async def _update(self, message):
        if not await self._can_manage_modules(message.author, message.guild):
            embed = response_engine.failure(
                title="Insufficient Permissions",
                description="Only the server owner can update the bot."
            )
            return await message.channel.send(embed=embed)
        # Create initial embed for update
        embed = response_engine.build(
            title="Updating Shorekeeper",
            description="Checking...",
            color=0x5865F2
        )
        status = await message.channel.send(embed=embed)
        embed.description = "Checking...\nMigrating..."
        await status.edit(embed=embed)
        get_guild_config(message.guild.id)
        embed.description = "Checking...\nMigrating...\nApplying..."
        await status.edit(embed=embed)
        if hasattr(self.bot, "sync_visible_commands"):
            await self.bot.sync_visible_commands(message.guild)
        cfg = get_guild_config(message.guild.id)
        enabled = [
            module for module in module_names()
            if get_module_state(cfg, module) in {"active", "debug"}
        ]
        enabled_str = "`, `".join(enabled)
        # Update to final
        embed.description = (
            "Checking...\nMigrating...\nApplying...\nComplete.\n\n"
            f"Enabled modules: `{enabled_str}`"
        )
        await status.edit(embed=embed)


async def setup(bot):
    await bot.add_cog(ModuleManager(bot))