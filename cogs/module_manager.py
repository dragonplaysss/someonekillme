import os
import platform

import discord
from discord import app_commands
from discord.ext import commands

from cogs.module_registry import (
    MODULES,
    get_module_state,
    module_names,
    normalize_module_name,
    set_module_state,
)
from cogs.server_config import get_guild_config, is_admin, is_owner_id, update_guild_config
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
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
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


class ModuleManager(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def _module_lines(self, guild):
        cfg = get_guild_config(guild.id)
        lines = []
        for module in module_names():
            state = get_module_state(cfg, module).upper()
            loaded = self._module_loaded(module)
            marker = "loaded" if loaded else "not loaded"
            lines.append(f"`{module}`: **{state}** ({marker})")
        return lines

    def _module_loaded(self, module):
        meta = MODULES.get(module, {})
        extensions = meta.get("extensions") or [meta.get("extension")]
        return all(ext in self.bot.extensions for ext in extensions if ext)

    async def _set_module(self, interaction, module, state):
        if not interaction.guild:
            return await interaction.response.send_message("Use this in a server.", ephemeral=True)
        if not is_admin(interaction.user):
            return await interaction.response.send_message("No permission.", ephemeral=True)

        module = normalize_module_name(module)
        if module == "core" or module not in MODULES:
            return await interaction.response.send_message(
                f"Unknown module. Available: `{', '.join(module_names())}`",
                ephemeral=True,
            )

        def updater(config):
            set_module_state(config, module, state)

        update_guild_config(interaction.guild.id, updater)
        await interaction.response.defer(ephemeral=True, thinking=True)
        syncer = getattr(self.bot, "sync_visible_commands", None)
        if syncer:
            await syncer(interaction.guild)
        await interaction.followup.send(
            f"`{module}` is now **{state.upper()}**.\nSlash commands were synced for this server.",
            ephemeral=True,
        )

    @app_commands.command(name="enablecommands", description="Enable and show a module's slash commands.")
    async def enablecommands(self, interaction: discord.Interaction, module: str):
        await self._set_module(interaction, module, "active")

    @app_commands.command(name="disablecommands", description="Hide a module's slash commands while keeping mention commands.")
    async def disablecommands(self, interaction: discord.Interaction, module: str):
        await self._set_module(interaction, module, "hidden")

    @app_commands.command(name="status", description="Show Shorekeeper module status.")
    async def status(self, interaction: discord.Interaction):
        if not interaction.guild:
            return await interaction.response.send_message("Use this in a server.", ephemeral=True)
        embed = discord.Embed(title="Shorekeeper Status", color=0x5865F2)
        embed.description = "\n".join(self._module_lines(interaction.guild))
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="settings", description="Show server configuration summary.")
    async def settings(self, interaction: discord.Interaction):
        if not interaction.guild:
            return await interaction.response.send_message("Use this in a server.", ephemeral=True)
        cfg = get_guild_config(interaction.guild.id)
        embed = discord.Embed(title="Server Settings", color=0x2ECC71)
        embed.add_field(name="Modules", value="\n".join(self._module_lines(interaction.guild))[:1024], inline=False)
        embed.add_field(name="Channels", value=str(cfg.get("channels", {}))[:1024], inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="help", description="Show Shorekeeper handoff commands.")
    async def help(self, interaction: discord.Interaction):
        text = (
            "Core slash commands: `/help`, `/settings`, `/status`, `/enablecommands`, `/disablecommands`.\n"
            "Mention tools: `@Shorekeeper health`, `@Shorekeeper update`, "
            "`@Shorekeeper module debug <module>`, `@Shorekeeper module recover`."
        )
        await interaction.response.send_message(text, ephemeral=True)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        trigger = parse_shorekeeper_trigger(self.bot, message)
        if not trigger:
            return

        keyword = trigger["keyword"]
        if keyword == "health":
            return await self._health(message)
        if keyword == "update":
            return await self._update(message)
        if keyword == "resync":
            return await self._resync(message)
        if keyword == "module":
            return await self._module_command(message, trigger)

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

        embed = discord.Embed(title="Health Check", color=0x57F287 if not missing_channels else 0xFEE75C)
        embed.add_field(name="Loaded Cogs", value=str(len(self.bot.cogs)), inline=True)
        embed.add_field(name="Extensions", value=str(len(self.bot.extensions)), inline=True)
        embed.add_field(name="RAM", value=f"{_ram_mb()} MB", inline=True)
        embed.add_field(name="Python", value=platform.python_version(), inline=True)
        embed.add_field(name="Missing Channels", value="\n".join(missing_channels) or "None", inline=False)
        embed.add_field(name="Broken Webhooks", value="\n".join(broken_webhooks[:10]) or "None found", inline=False)
        await message.channel.send(embed=embed)

    async def _resync(self, message):
        if not is_owner_id(message.guild.id, message.author.id):
            return await message.channel.send("Owner only.")

        status = await message.channel.send("Clearing slash command tree...")
        if hasattr(self.bot, "_restore_tree_commands"):
            self.bot._restore_tree_commands()
        if hasattr(self.bot, "remember_app_commands"):
            self.bot.remember_app_commands()

        await status.edit(content="Rebuilding slash command tree...")
        synced_count = 0
        if hasattr(self.bot, "sync_visible_commands"):
            synced_count = await self.bot.sync_visible_commands(message.guild, reason="owner resync")

        health = getattr(self.bot, "slash_health", {})
        await status.edit(
            content=(
                "Slash commands resynced.\n"
                f"registered={health.get('registered', 0)} "
                f"visible={health.get('visible', 0)} "
                f"synced={synced_count}"
            )
        )

    async def _module_command(self, message, trigger):
        if not is_admin(message.author):
            return await message.channel.send("No permission.")
        args = trigger["args"]
        if not args:
            return await message.channel.send("Use `module debug <module>` or `module recover`.")
        action = args[0].lower()
        if action in {"debug", "disable", "hidden", "active"}:
            module = normalize_module_name(args[1] if len(args) > 1 else "")
            if module not in MODULES or module == "core":
                return await message.channel.send(f"Unknown module. Available: `{', '.join(module_names())}`")
            state = {"disable": "disabled", "hidden": "hidden", "active": "active", "debug": "debug"}[action]

            def updater(config):
                set_module_state(config, module, state)

            update_guild_config(message.guild.id, updater)
            syncer = getattr(self.bot, "sync_visible_commands", None)
            if syncer:
                await syncer(message.guild)
            return await message.channel.send(f"`{module}` is now **{state.upper()}**.")

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
            return await message.channel.send(
                "Module recovery complete.\n"
                f"Loaded: `{len(loaded)}`\n"
                f"Failed: `{len(failed)}`" + (("\n" + "\n".join(failed[:5])) if failed else "")
            )

        return await message.channel.send("Unknown module action.")

    async def _update(self, message):
        if not is_admin(message.author):
            return await message.channel.send("No permission.")
        status = await message.channel.send("Checking...")
        await status.edit(content="Checking...\nMigrating...")
        get_guild_config(message.guild.id)
        await status.edit(content="Checking...\nMigrating...\nApplying...")
        if hasattr(self.bot, "sync_visible_commands"):
            await self.bot.sync_visible_commands(message.guild)
        cfg = get_guild_config(message.guild.id)
        enabled = [
            module for module in module_names()
            if get_module_state(cfg, module) in {"active", "debug"}
        ]
        await status.edit(
            content=(
                "Checking...\nMigrating...\nApplying...\nComplete.\n\n"
                "Enabled modules: `" + "`, `".join(enabled) + "`"
            )
        )


async def setup(bot):
    await bot.add_cog(ModuleManager(bot))
