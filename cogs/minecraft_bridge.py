import asyncio
import random
import re
import string
import time
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands

from cogs.module_registry import MINECRAFT_GUILD_ID
from cogs.server_config import get_guild_config, is_panel_owner, load_config, update_guild_config

try:
    import psutil
except ImportError:
    psutil = None


SCREEN_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
CHAT_RE = re.compile(r"\]: <([^>]+)> (.*)$")
LIST_RE = re.compile(r"There are (\d+) of a max of \d+ players online: ?(.*)$")
PLAYER_EVENT_RE = re.compile(r"\]: ([A-Za-z0-9_]{1,16}) (joined|left) the game$")
ADVANCEMENT_RE = re.compile(r"\]: ([A-Za-z0-9_]{1,16}) has (?:made the advancement|completed the challenge|reached the goal) \[(.+)]$")
USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{3,16}$")
VERIFY_CODE_TTL = 600
CHAT_WEBHOOK_NAME = "Shorekeeper Minecraft Chat"
DEATH_HINTS = (
    " was slain by ",
    " was shot by ",
    " was killed by ",
    " was blown up",
    " hit the ground",
    " fell ",
    " drowned",
    " burned to death",
    " went up in flames",
    " tried to swim in lava",
    " was doomed to fall",
    " was fireballed",
    " was pricked to death",
    " starved to death",
    " suffocated in a wall",
    " was squashed by ",
    " was poked to death",
    " experienced kinetic energy",
)


def _minecraft_defaults():
    return {
        "enabled": False,
        "screen_name": "minecraft",
        "chat_channel": None,
        "console_channel": None,
        "server_directory": "/home/ubuntu/minecraft",
        "start_command": "java -Xms2G -Xmx4G -jar server.jar nogui",
        "links": {},
        "pending_verifications": {},
        "verified_minecraft_role": None,
    }


def _clean_text(value, limit=500):
    text = str(value or "")
    text = text.replace("\r", " ").replace("\n", " ")
    text = "".join(ch for ch in text if ord(ch) >= 32)
    return text.strip()[:limit]


def _clean_screen_name(value):
    name = _clean_text(value, 64) or "minecraft"
    if not SCREEN_NAME_RE.fullmatch(name):
        raise ValueError("Screen name may only contain letters, numbers, `_`, `.`, and `-`.")
    return name


def _format_uptime(seconds):
    seconds = max(0, int(seconds))
    days, seconds = divmod(seconds, 86400)
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours or days:
        parts.append(f"{hours}h")
    parts.append(f"{minutes}m")
    return " ".join(parts) if parts else f"{seconds}s"


def _clean_discord_chat(message):
    content = message.clean_content
    content = re.sub(r"<a?:([A-Za-z0-9_]+):\d+>", r":\1:", content)
    if message.attachments:
        urls = " ".join(attachment.url for attachment in message.attachments[:3])
        content = f"{content} {urls}".strip()
    return _clean_text(content, 240)


class MinecraftBridge(commands.Cog):
    mc = app_commands.Group(
        name="mc",
        description="Minecraft server bridge.",
        guild_ids=[MINECRAFT_GUILD_ID],
    )
    mcsetup = app_commands.Group(
        name="mcsetup",
        description="Configure the Minecraft bridge.",
        guild_ids=[MINECRAFT_GUILD_ID],
    )

    def __init__(self, bot):
        self.bot = bot
        self.log_task = None
        self.log_state = {}
        self.players = {}
        self.started_at = {}
        self.last_status = {}
        self.webhook_cache = {}

    async def cog_load(self):
        self.log_task = asyncio.create_task(self._monitor_logs())

    async def cog_unload(self):
        if self.log_task:
            self.log_task.cancel()
            try:
                await self.log_task
            except asyncio.CancelledError:
                pass

    def _minecraft_config(self, guild_id):
        cfg = get_guild_config(guild_id)
        minecraft = cfg.setdefault("minecraft", _minecraft_defaults())
        for key, value in _minecraft_defaults().items():
            minecraft.setdefault(key, value)
        if not isinstance(minecraft.get("links"), dict):
            minecraft["links"] = {}
        if not isinstance(minecraft.get("pending_verifications"), dict):
            minecraft["pending_verifications"] = {}
        return minecraft

    def _username_key(self, username):
        return _clean_text(username, 16).lower()

    def _avatar_url(self, username):
        return f"https://mc-heads.net/avatar/{_clean_text(username, 16)}"

    def _minecraft_links(self, cfg):
        links = cfg.setdefault("links", {})
        return links if isinstance(links, dict) else {}

    def _linked_record(self, guild_id, username):
        cfg = self._minecraft_config(guild_id)
        return self._minecraft_links(cfg).get(self._username_key(username))

    def _linked_mention(self, guild_id, username):
        record = self._linked_record(guild_id, username)
        if not record:
            return "Not linked"
        return f"<@{record.get('discord_id')}>"

    def _discord_link(self, cfg, discord_id):
        for record in self._minecraft_links(cfg).values():
            if int(record.get("discord_id", 0)) == int(discord_id):
                return record
        return None

    def _expire_codes_in_config(self, minecraft):
        now = time.time()
        pending = minecraft.setdefault("pending_verifications", {})
        expired = [
            code
            for code, record in pending.items()
            if now - float(record.get("created_at", 0)) > VERIFY_CODE_TTL
        ]
        for code in expired:
            pending.pop(code, None)
        return bool(expired)

    def _new_verification_code(self, pending):
        alphabet = string.ascii_uppercase + string.digits
        for _ in range(100):
            code = "".join(random.choice(alphabet) for _ in range(5))
            if code not in pending:
                return code
        raise RuntimeError("Could not generate a unique verification code.")

    def _enabled_config(self, guild):
        if not guild:
            return None, "Use this in a server."
        if guild.id != MINECRAFT_GUILD_ID:
            return None, "Minecraft bridge is not available in this server."
        cfg = self._minecraft_config(guild.id)
        if not cfg.get("enabled"):
            return None, "Minecraft bridge is disabled. Use `/mcsetup enable` first."
        return cfg, None

    async def _require_panel_owner(self, interaction):
        if not interaction.guild:
            await interaction.response.send_message("Use this in a server.", ephemeral=True)
            return False
        if interaction.guild.id != MINECRAFT_GUILD_ID:
            await interaction.response.send_message("Minecraft bridge is not available in this server.", ephemeral=True)
            return False
        if not is_panel_owner(interaction.user.id):
            await interaction.response.send_message("Only the panel owner can use this.", ephemeral=True)
            return False
        return True

    async def _require_enabled_owner(self, interaction):
        if not await self._require_panel_owner(interaction):
            return None
        cfg, error = self._enabled_config(interaction.guild)
        if error:
            await interaction.response.send_message(error, ephemeral=True)
            return None
        return cfg

    async def _run_exec(self, *args, cwd=None, timeout=12):
        proc = await asyncio.create_subprocess_exec(
            *args,
            cwd=str(cwd) if cwd else None,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            stdout, stderr = await proc.communicate()
            raise TimeoutError(f"`{args[0]}` timed out.")
        return proc.returncode, stdout.decode(errors="replace"), stderr.decode(errors="replace")

    async def _screen_exists(self, screen_name):
        try:
            code, stdout, stderr = await self._run_exec("screen", "-ls", timeout=5)
        except (FileNotFoundError, TimeoutError):
            return False
        output = f"{stdout}\n{stderr}"
        return bool(re.search(rf"(^|\s)\d+\.{re.escape(screen_name)}(\s|$)", output))

    async def _send_to_screen(self, cfg, command):
        screen_name = _clean_screen_name(cfg.get("screen_name"))
        safe_command = _clean_text(command, 500)
        if not safe_command:
            raise ValueError("Command cannot be empty.")
        code, _, stderr = await self._run_exec(
            "screen",
            "-S",
            screen_name,
            "-X",
            "stuff",
            f"{safe_command}\n",
            timeout=5,
        )
        if code != 0:
            raise RuntimeError(_clean_text(stderr, 300) or "Could not write to the screen session.")

    async def _start_server(self, guild_id, cfg):
        screen_name = _clean_screen_name(cfg.get("screen_name"))
        start_command = _clean_text(cfg.get("start_command"), 1000)
        if not start_command:
            return False, "No start command is configured."
        if any(ord(ch) < 32 for ch in start_command):
            return False, "Start command contains invalid control characters."
        if not await self._screen_exists(screen_name):
            return False, f"Screen session `{screen_name}` was not found."
        await self._send_to_screen(cfg, start_command)
        self.started_at[guild_id] = time.time()
        return True, "Minecraft server start command was written to the screen session."

    async def _stop_server(self, cfg):
        await self._send_to_screen(cfg, "stop")

    def _embed(self, title, description=None, color=0x57F287):
        return discord.Embed(title=title, description=description, color=color)

    async def _send_embed(self, interaction, title, description=None, color=0x57F287, ephemeral=True):
        embed = self._embed(title, description, color)
        if interaction.response.is_done():
            await interaction.followup.send(embed=embed, ephemeral=ephemeral)
        else:
            await interaction.response.send_message(embed=embed, ephemeral=ephemeral)

    async def _grant_verified_role(self, guild, member, cfg):
        role_id = cfg.get("verified_minecraft_role")
        if not role_id or not isinstance(member, discord.Member):
            return False
        role = guild.get_role(int(role_id))
        if not role or role in member.roles:
            return False
        try:
            await member.add_roles(role, reason="Minecraft account verified with Shorekeeper")
            return True
        except (discord.Forbidden, discord.HTTPException):
            return False

    async def get_or_create_chat_webhook(self, channel):
        cached_id = self.webhook_cache.get(channel.id)
        try:
            webhooks = await channel.webhooks()
        except (discord.Forbidden, discord.HTTPException):
            return None

        if cached_id:
            for webhook in webhooks:
                if webhook.id == cached_id:
                    return webhook

        for webhook in webhooks:
            if webhook.name == CHAT_WEBHOOK_NAME:
                self.webhook_cache[channel.id] = webhook.id
                return webhook

        try:
            webhook = await channel.create_webhook(name=CHAT_WEBHOOK_NAME)
        except (discord.Forbidden, discord.HTTPException):
            return None
        self.webhook_cache[channel.id] = webhook.id
        return webhook

    async def send_mc_webhook(self, guild_id, channel_id, username, content):
        if not channel_id:
            return
        guild = self.bot.get_guild(guild_id)
        channel = guild.get_channel(channel_id) if guild else self.bot.get_channel(channel_id)
        if not isinstance(channel, discord.TextChannel):
            return
        webhook = await self.get_or_create_chat_webhook(channel)
        if not webhook:
            return
        try:
            await webhook.send(
                _clean_text(content, 1800),
                username=_clean_text(username, 32),
                avatar_url=self._avatar_url(username),
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except (discord.Forbidden, discord.HTTPException):
            return

    def _find_server_process(self, cfg):
        if psutil is None:
            return None
        server_directory = str(Path(_clean_text(cfg.get("server_directory"), 300)).expanduser())
        screen_name = _clean_text(cfg.get("screen_name"), 64)
        best = None
        for proc in psutil.process_iter(["pid", "name", "cmdline", "create_time", "memory_info"]):
            try:
                name = (proc.info.get("name") or "").lower()
                cmdline = " ".join(proc.info.get("cmdline") or [])
                cwd = ""
                try:
                    cwd = proc.cwd()
                except (psutil.AccessDenied, psutil.NoSuchProcess):
                    pass
                is_java = "java" in name or "java" in cmdline.lower()
                matches_dir = server_directory and (cwd == server_directory or server_directory in cmdline)
                matches_screen = screen_name and screen_name in cmdline
                if is_java and (matches_dir or matches_screen):
                    if not best or proc.info.get("create_time", 0) > best.info.get("create_time", 0):
                        best = proc
            except (psutil.AccessDenied, psutil.NoSuchProcess):
                continue
        return best

    async def _status_fields(self, guild_id, cfg):
        screen_name = _clean_screen_name(cfg.get("screen_name"))
        online = await self._screen_exists(screen_name)
        proc = self._find_server_process(cfg)
        uptime = "unknown"
        ram = "unknown"
        cpu = "unknown"
        if proc:
            try:
                uptime = _format_uptime(time.time() - proc.create_time())
                ram = f"{proc.memory_info().rss / (1024 * 1024):.1f} MB"
                cpu = f"{proc.cpu_percent(interval=0.2):.1f}%"
            except (psutil.AccessDenied, psutil.NoSuchProcess):
                pass
        elif psutil is None:
            ram = "psutil not installed"
            cpu = "psutil not installed"
        elif guild_id in self.started_at:
            uptime = _format_uptime(time.time() - self.started_at[guild_id])
        player_names = sorted(self.players.get(guild_id, set()))
        return online, uptime, ram, cpu, player_names

    def _server_version(self, guild_id):
        return self.last_status.get(guild_id, {}).get("version") or "Unknown"

    def _update_version_from_line(self, guild_id, line):
        match = re.search(r"Starting minecraft server version (.+)$", line, re.IGNORECASE)
        if not match:
            return
        self.last_status.setdefault(guild_id, {})["version"] = _clean_text(match.group(1), 80)

    @mc.command(name="console", description="Send a command directly to the Minecraft console.")
    async def mc_console(self, interaction: discord.Interaction, command: str):
        cfg = await self._require_enabled_owner(interaction)
        if not cfg:
            return
        try:
            await self._send_to_screen(cfg, command)
        except Exception as exc:
            return await self._send_embed(interaction, "Console Command Failed", str(exc), 0xED4245)
        await self._send_embed(interaction, "Console Command Sent", f"`{_clean_text(command, 200)}`")

    @mc.command(name="start", description="Start the Minecraft server screen session.")
    async def mc_start(self, interaction: discord.Interaction):
        cfg = await self._require_enabled_owner(interaction)
        if not cfg:
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            ok, message = await self._start_server(interaction.guild.id, cfg)
        except Exception as exc:
            ok, message = False, str(exc)
        await interaction.followup.send(embed=self._embed("Minecraft Start", message, 0x57F287 if ok else 0xFEE75C), ephemeral=True)

    @mc.command(name="stop", description="Stop the Minecraft server.")
    async def mc_stop(self, interaction: discord.Interaction):
        cfg = await self._require_enabled_owner(interaction)
        if not cfg:
            return
        try:
            await self._stop_server(cfg)
        except Exception as exc:
            return await self._send_embed(interaction, "Minecraft Stop Failed", str(exc), 0xED4245)
        await self._send_embed(interaction, "Minecraft Stop", "`stop` was sent to the server.")

    @mc.command(name="restart", description="Restart the Minecraft server.")
    async def mc_restart(self, interaction: discord.Interaction):
        cfg = await self._require_enabled_owner(interaction)
        if not cfg:
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            await self._stop_server(cfg)
        except Exception as exc:
            return await interaction.followup.send(embed=self._embed("Restart Failed", str(exc), 0xED4245), ephemeral=True)

        screen_name = _clean_screen_name(cfg.get("screen_name"))
        for _ in range(30):
            await asyncio.sleep(1)
            if not await self._screen_exists(screen_name):
                break
        try:
            ok, message = await self._start_server(interaction.guild.id, cfg)
        except Exception as exc:
            ok, message = False, str(exc)
        await interaction.followup.send(embed=self._embed("Minecraft Restart", message, 0x57F287 if ok else 0xED4245), ephemeral=True)

    @mc.command(name="status", description="Show Minecraft server status.")
    async def mc_status(self, interaction: discord.Interaction):
        cfg, error = self._enabled_config(interaction.guild)
        if error:
            return await interaction.response.send_message(error, ephemeral=True)
        await interaction.response.defer(ephemeral=True, thinking=True)
        online, uptime, ram, cpu, player_names = await self._status_fields(interaction.guild.id, cfg)
        embed = self._embed("\U0001f3ae Minecraft Server", color=0x57F287 if online else 0xED4245)
        embed.add_field(name="Status", value="Online" if online else "Offline", inline=True)
        embed.add_field(name="Players", value=str(len(player_names)), inline=True)
        embed.add_field(name="TPS", value="Unavailable", inline=True)
        player_list = ", ".join(f"`{name}`" for name in player_names)
        embed.add_field(name="Player List", value=player_list[:1024] if player_list else "No players online.", inline=False)
        embed.add_field(name="RAM", value=ram, inline=True)
        embed.add_field(name="CPU", value=cpu, inline=True)
        embed.add_field(name="Version", value=self._server_version(interaction.guild.id), inline=True)
        embed.add_field(name="Uptime", value=uptime, inline=True)
        await interaction.followup.send(embed=embed, ephemeral=True)

    @mc.command(name="players", description="Show currently known online Minecraft players.")
    async def mc_players(self, interaction: discord.Interaction):
        cfg, error = self._enabled_config(interaction.guild)
        if error:
            return await interaction.response.send_message(error, ephemeral=True)
        players = sorted(self.players.get(interaction.guild.id, set()))
        embed = self._embed("Minecraft Players", color=0x5865F2)
        embed.add_field(name="Online", value=str(len(players)), inline=True)
        if players:
            embed.set_thumbnail(url=self._avatar_url(players[0]))
        else:
            embed.description = "No players are currently known online."
        for player in players[:12]:
            record = self._linked_record(interaction.guild.id, player)
            linked = self._linked_mention(interaction.guild.id, player) if record else "Not linked"
            verified = "Verified" if record else "Unverified"
            embed.add_field(
                name=player,
                value=f"Status: **{verified}**\nLinked Discord: {linked}\nAvatar: [Minecraft head]({self._avatar_url(player)})",
                inline=False,
            )
        if len(players) > 12:
            embed.set_footer(text=f"{len(players) - 12} more player(s) not shown.")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.guilds(MINECRAFT_GUILD_ID)
    @app_commands.command(name="mcverify", description="Verify your Minecraft account with a Shorekeeper code.")
    async def mcverify(self, interaction: discord.Interaction, code: str):
        cfg, error = self._enabled_config(interaction.guild)
        if error:
            return await interaction.response.send_message(error, ephemeral=True)
        verify_code = _clean_text(code, 12).upper()
        if not verify_code:
            return await interaction.response.send_message("Enter the verification code shown in Minecraft.", ephemeral=True)

        result = {"ok": False, "message": "That verification code is invalid or expired.", "username": None}

        def updater(config):
            minecraft = config.setdefault("minecraft", _minecraft_defaults())
            for key, value in _minecraft_defaults().items():
                minecraft.setdefault(key, value)
            self._expire_codes_in_config(minecraft)
            pending = minecraft.setdefault("pending_verifications", {})
            record = pending.get(verify_code)
            if not record:
                return
            username = _clean_text(record.get("username"), 16)
            if not username:
                pending.pop(verify_code, None)
                return
            links = minecraft.setdefault("links", {})
            username_key = self._username_key(username)
            existing_discord = self._discord_link(minecraft, interaction.user.id)
            if existing_discord and self._username_key(existing_discord.get("minecraft_username")) != username_key:
                result["message"] = f"You are already linked to `{existing_discord.get('minecraft_username')}`. Use `/unlinkmc` first."
                return
            existing_user = links.get(username_key)
            if existing_user and int(existing_user.get("discord_id", 0)) != interaction.user.id:
                if not is_panel_owner(interaction.user.id):
                    result["message"] = f"`{username}` is already linked to another Discord account."
                    return
            links[username_key] = {
                "minecraft_username": username,
                "discord_id": interaction.user.id,
                "verified_at": time.time(),
            }
            pending.pop(verify_code, None)
            result.update({"ok": True, "username": username, "message": f"`{username}` is now linked to your Discord account."})

        update_guild_config(interaction.guild.id, updater)
        if result["ok"]:
            await self._grant_verified_role(interaction.guild, interaction.user, cfg)
        color = 0x57F287 if result["ok"] else 0xED4245
        await self._send_embed(interaction, "Minecraft Verification", result["message"], color)

    @app_commands.guilds(MINECRAFT_GUILD_ID)
    @app_commands.command(name="unlinkmc", description="Unlink your Minecraft account.")
    async def unlinkmc(self, interaction: discord.Interaction, user: discord.Member = None):
        if not interaction.guild:
            return await interaction.response.send_message("Use this in a server.", ephemeral=True)
        if interaction.guild.id != MINECRAFT_GUILD_ID:
            return await interaction.response.send_message("Minecraft bridge is not available in this server.", ephemeral=True)
        target = user if user and is_panel_owner(interaction.user.id) else interaction.user
        removed = {"name": None}

        def updater(config):
            minecraft = config.setdefault("minecraft", _minecraft_defaults())
            links = minecraft.setdefault("links", {})
            for key, record in list(links.items()):
                if int(record.get("discord_id", 0)) == target.id:
                    removed["name"] = record.get("minecraft_username")
                    links.pop(key, None)
                    break

        update_guild_config(interaction.guild.id, updater)
        if removed["name"]:
            return await self._send_embed(interaction, "Minecraft Link Removed", f"`{removed['name']}` is no longer linked to {target.mention}.")
        await self._send_embed(interaction, "Minecraft Link", f"{target.mention} has no Minecraft link.", 0xFEE75C)

    @app_commands.guilds(MINECRAFT_GUILD_ID)
    @app_commands.command(name="mclinkinfo", description="Show your Minecraft link.")
    async def mclinkinfo(self, interaction: discord.Interaction, user: discord.Member = None):
        if not interaction.guild:
            return await interaction.response.send_message("Use this in a server.", ephemeral=True)
        if interaction.guild.id != MINECRAFT_GUILD_ID:
            return await interaction.response.send_message("Minecraft bridge is not available in this server.", ephemeral=True)
        target = user if user and is_panel_owner(interaction.user.id) else interaction.user
        cfg = self._minecraft_config(interaction.guild.id)
        record = self._discord_link(cfg, target.id)
        if not record:
            return await self._send_embed(interaction, "Minecraft Link", f"{target.mention} is not linked.", 0xFEE75C)
        username = record.get("minecraft_username")
        embed = self._embed("Minecraft Link", color=0x5865F2)
        embed.set_thumbnail(url=self._avatar_url(username))
        embed.add_field(name="Discord", value=target.mention, inline=True)
        embed.add_field(name="Minecraft", value=f"`{username}`", inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @mcsetup.command(name="enable", description="Enable the Minecraft bridge.")
    async def mcsetup_enable(self, interaction: discord.Interaction):
        if not await self._require_panel_owner(interaction):
            return

        def updater(config):
            minecraft = config.setdefault("minecraft", _minecraft_defaults())
            minecraft["enabled"] = True

        update_guild_config(interaction.guild.id, updater)
        syncer = getattr(self.bot, "sync_visible_commands", None)
        if syncer:
            await interaction.response.defer(ephemeral=True, thinking=True)
            await syncer(interaction.guild, reason="minecraft enabled")
            return await interaction.followup.send(embed=self._embed("Minecraft Bridge Enabled", "Commands were synced for this server."), ephemeral=True)
        await self._send_embed(interaction, "Minecraft Bridge Enabled")

    @mcsetup.command(name="disable", description="Disable the Minecraft bridge.")
    async def mcsetup_disable(self, interaction: discord.Interaction):
        if not await self._require_panel_owner(interaction):
            return

        def updater(config):
            minecraft = config.setdefault("minecraft", _minecraft_defaults())
            minecraft["enabled"] = False

        update_guild_config(interaction.guild.id, updater)
        await self._send_embed(interaction, "Minecraft Bridge Disabled", "Log and chat relays will stop.")

    @mcsetup.command(name="chatchannel", description="Set the Discord channel for Minecraft chat.")
    async def mcsetup_chatchannel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        if not await self._require_panel_owner(interaction):
            return

        def updater(config):
            config.setdefault("minecraft", _minecraft_defaults())["chat_channel"] = channel.id

        update_guild_config(interaction.guild.id, updater)
        await self._send_embed(interaction, "Minecraft Chat Channel", f"Chat relay set to {channel.mention}.")

    @mcsetup.command(name="consolechannel", description="Set the Discord channel for Minecraft console events.")
    async def mcsetup_consolechannel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        if not await self._require_panel_owner(interaction):
            return

        def updater(config):
            config.setdefault("minecraft", _minecraft_defaults())["console_channel"] = channel.id

        update_guild_config(interaction.guild.id, updater)
        await self._send_embed(interaction, "Minecraft Console Channel", f"Console events set to {channel.mention}.")

    @mcsetup.command(name="screen", description="Set the Linux screen session name.")
    async def mcsetup_screen(self, interaction: discord.Interaction, screen_name: str):
        if not await self._require_panel_owner(interaction):
            return
        try:
            clean_name = _clean_screen_name(screen_name)
        except ValueError as exc:
            return await self._send_embed(interaction, "Invalid Screen Name", str(exc), 0xED4245)

        def updater(config):
            config.setdefault("minecraft", _minecraft_defaults())["screen_name"] = clean_name

        update_guild_config(interaction.guild.id, updater)
        await self._send_embed(interaction, "Minecraft Screen", f"Screen session set to `{clean_name}`.")

    @mcsetup.command(name="directory", description="Set the Minecraft server directory.")
    async def mcsetup_directory(self, interaction: discord.Interaction, server_directory: str):
        if not await self._require_panel_owner(interaction):
            return
        clean_directory = _clean_text(server_directory, 300)
        if not clean_directory:
            return await self._send_embed(interaction, "Invalid Directory", "Directory cannot be empty.", 0xED4245)

        def updater(config):
            config.setdefault("minecraft", _minecraft_defaults())["server_directory"] = clean_directory

        update_guild_config(interaction.guild.id, updater)
        await self._send_embed(interaction, "Minecraft Directory", f"Server directory set to `{clean_directory}`.")

    @mcsetup.command(name="verifiedrole", description="Set the role given after Minecraft verification.")
    async def mcsetup_verifiedrole(self, interaction: discord.Interaction, role: discord.Role = None):
        if not await self._require_panel_owner(interaction):
            return

        def updater(config):
            config.setdefault("minecraft", _minecraft_defaults())["verified_minecraft_role"] = role.id if role else None

        update_guild_config(interaction.guild.id, updater)
        value = role.mention if role else "disabled"
        await self._send_embed(interaction, "Minecraft Verified Role", f"Verified role is now {value}.")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        if message.guild.id != MINECRAFT_GUILD_ID:
            return
        cfg = self._minecraft_config(message.guild.id)
        if not cfg.get("enabled") or message.channel.id != cfg.get("chat_channel"):
            return
        content = _clean_discord_chat(message)
        if not content:
            return
        link = self._discord_link(cfg, message.author.id)
        display_name = _clean_text(message.author.display_name, 32) or "Discord"
        if link:
            username = f"{display_name} ({_clean_text(link.get('minecraft_username'), 16)})"
        else:
            username = display_name
        try:
            await self._send_to_screen(cfg, f"say [Discord] {username}: {content}")
        except Exception:
            return

    async def _monitor_logs(self):
        await self.bot.wait_until_ready()
        while not self.bot.is_closed():
            try:
                await self._poll_all_logs()
            except Exception as exc:
                print(f"[MinecraftBridge] log monitor error: {type(exc).__name__}: {exc}")
            await asyncio.sleep(1)

    async def _poll_all_logs(self):
        config = load_config()
        for gid, guild_config in config.get("guilds", {}).items():
            if not gid.isdigit():
                continue
            if int(gid) != MINECRAFT_GUILD_ID:
                continue
            minecraft = guild_config.get("minecraft") or {}
            if not minecraft.get("enabled"):
                continue
            guild_id = int(gid)
            if self._has_expired_codes(minecraft):
                self._expire_codes(guild_id)
            latest_log = Path(_clean_text(minecraft.get("server_directory"), 300)).expanduser() / "logs" / "latest.log"
            await self._poll_log(guild_id, latest_log, minecraft)

    def _has_expired_codes(self, minecraft):
        now = time.time()
        pending = minecraft.get("pending_verifications") or {}
        return any(now - float(record.get("created_at", 0)) > VERIFY_CODE_TTL for record in pending.values())

    def _expire_codes(self, guild_id):
        changed = {"value": False}

        def updater(config):
            minecraft = config.setdefault("minecraft", _minecraft_defaults())
            changed["value"] = self._expire_codes_in_config(minecraft)

        update_guild_config(guild_id, updater)
        return changed["value"]

    async def _poll_log(self, guild_id, path, cfg):
        try:
            stat = path.stat()
        except OSError:
            return
        new_state = guild_id not in self.log_state
        state = self.log_state.setdefault(guild_id, {"path": path, "pos": 0, "stamp": stat.st_mtime})
        if state.get("path") != path or stat.st_size < state.get("pos", 0):
            state.update({"path": path, "pos": 0, "stamp": stat.st_mtime})
            new_state = True
        if stat.st_size == state.get("pos", 0):
            return

        with path.open("r", encoding="utf-8", errors="replace") as handle:
            handle.seek(state.get("pos", 0))
            lines = handle.readlines()
            state["pos"] = handle.tell()
            state["stamp"] = stat.st_mtime

        for line in lines:
            await self._handle_log_line(guild_id, line.strip(), cfg, announce=not new_state)

    async def _handle_log_line(self, guild_id, line, cfg, announce=True):
        if not line:
            return
        list_match = LIST_RE.search(line)
        if list_match:
            names = [name.strip() for name in list_match.group(2).split(",") if name.strip()]
            self.players[guild_id] = set(names)
            return

        self._update_version_from_line(guild_id, line)
        chat_match = CHAT_RE.search(line)
        if chat_match:
            player = _clean_text(chat_match.group(1), 32)
            message = _clean_text(chat_match.group(2), 1500)
            if player and message:
                self.players.setdefault(guild_id, set()).add(player)
                if announce:
                    await self.send_mc_webhook(guild_id, cfg.get("chat_channel"), player, message)
            return

        await self._handle_event_line(guild_id, line, cfg, announce=announce)

    async def _handle_event_line(self, guild_id, line, cfg, announce=True):
        event_match = PLAYER_EVENT_RE.search(line)
        if event_match:
            player, action = event_match.groups()
            if action == "joined":
                self.players.setdefault(guild_id, set()).add(player)
                if announce and not self._linked_record(guild_id, player):
                    await self._start_verification(guild_id, cfg, player)
                    return
                if announce:
                    await self._send_player_event_embed(guild_id, cfg.get("console_channel"), "join", player)
                return
            self.players.setdefault(guild_id, set()).discard(player)
            if announce:
                await self._send_player_event_embed(guild_id, cfg.get("console_channel"), "leave", player)
            return

        advancement = ADVANCEMENT_RE.search(line)
        if advancement and announce:
            player, title = advancement.groups()
            await self._send_advancement_embed(guild_id, cfg.get("console_channel"), player, title)
            return

        message = line.split("]: ", 1)[-1]
        if "Done (" in message and "For help" in message:
            self.started_at[guild_id] = time.time()
            if announce:
                await self._send_server_state_embed(guild_id, cfg.get("console_channel"), online=True)
            return
        if "Stopping server" in message or "Stopping the server" in message or "Server stopped" in message:
            self.players[guild_id] = set()
            if announce:
                await self._send_server_state_embed(guild_id, cfg.get("console_channel"), online=False)
            return
        if any(hint in message for hint in DEATH_HINTS):
            if announce:
                await self._send_death_embed(guild_id, cfg.get("console_channel"), message)
            return

    async def _start_verification(self, guild_id, cfg, username):
        if not USERNAME_RE.fullmatch(username):
            return
        code_holder = {"code": None, "created": False}

        def updater(config):
            minecraft = config.setdefault("minecraft", _minecraft_defaults())
            for key, value in _minecraft_defaults().items():
                minecraft.setdefault(key, value)
            self._expire_codes_in_config(minecraft)
            pending = minecraft.setdefault("pending_verifications", {})
            for existing_code, record in pending.items():
                if self._username_key(record.get("username")) == self._username_key(username):
                    code_holder["code"] = existing_code
                    return
            code = self._new_verification_code(pending)
            pending[code] = {
                "code": code,
                "username": username,
                "created_at": time.time(),
            }
            code_holder.update({"code": code, "created": True})

        update_guild_config(guild_id, updater)
        code = code_holder["code"]
        if not code:
            return
        reason = (
            "Shorekeeper Verification Required"
            f"\\n\\nCode: {code}"
            f"\\n\\nRun:\\n/mcverify {code}"
        )
        try:
            await self._send_to_screen(cfg, f"kick {username} {reason}")
        except Exception as exc:
            print(f"[MinecraftBridge] verification kick failed for {username}: {type(exc).__name__}: {exc}")
            return
        if code_holder["created"]:
            await self._send_channel(
                guild_id,
                cfg.get("console_channel"),
                f"`{username}` needs verification. A 10-minute code was shown in-game.",
            )

    async def _send_player_event_embed(self, guild_id, channel_id, kind, username):
        title = "\U0001f7e2 Player Joined" if kind == "join" else "\U0001f534 Player Left"
        color = 0x57F287 if kind == "join" else 0xED4245
        embed = discord.Embed(title=title, color=color, timestamp=discord.utils.utcnow())
        embed.set_thumbnail(url=self._avatar_url(username))
        embed.add_field(name="Player", value=f"`{username}`", inline=True)
        embed.add_field(name="Linked Discord", value=self._linked_mention(guild_id, username), inline=True)
        embed.add_field(name="Players Online", value=str(len(self.players.get(guild_id, set()))), inline=True)
        await self._send_channel(guild_id, channel_id, embed=embed)

    async def _send_death_embed(self, guild_id, channel_id, message):
        player = _clean_text(message.split(" ", 1)[0], 16)
        cause = message[len(player):].strip() if player else message
        if cause:
            cause = cause[0].upper() + cause[1:]
        embed = discord.Embed(title="\u2620\ufe0f Player Death", color=0x2B2D31, timestamp=discord.utils.utcnow())
        if player:
            embed.set_thumbnail(url=self._avatar_url(player))
            embed.add_field(name="Player", value=f"`{player}`", inline=True)
            embed.add_field(name="Linked Discord", value=self._linked_mention(guild_id, player), inline=True)
        embed.add_field(name="Cause", value=_clean_text(cause or message, 500), inline=False)
        await self._send_channel(guild_id, channel_id, embed=embed)

    async def _send_advancement_embed(self, guild_id, channel_id, username, title):
        embed = discord.Embed(title="\U0001f3c6 Advancement Earned", color=0xFEE75C, timestamp=discord.utils.utcnow())
        embed.set_thumbnail(url=self._avatar_url(username))
        embed.add_field(name="Player", value=f"`{username}`", inline=True)
        embed.add_field(name="Linked Discord", value=self._linked_mention(guild_id, username), inline=True)
        embed.add_field(name="Advancement", value=_clean_text(title, 200), inline=False)
        await self._send_channel(guild_id, channel_id, embed=embed)

    async def _send_server_state_embed(self, guild_id, channel_id, online):
        title = "\U0001f7e2 Minecraft Server Online" if online else "\U0001f534 Minecraft Server Offline"
        color = 0x57F287 if online else 0xED4245
        embed = discord.Embed(title=title, color=color, timestamp=discord.utils.utcnow())
        embed.add_field(name="Status", value="Online" if online else "Offline", inline=True)
        embed.add_field(name="Players Online", value=str(len(self.players.get(guild_id, set()))), inline=True)
        embed.add_field(name="Version", value=self._server_version(guild_id), inline=True)
        await self._send_channel(guild_id, channel_id, embed=embed)

    async def _send_channel(self, guild_id, channel_id, content=None, embed=None):
        if not channel_id:
            return
        guild = self.bot.get_guild(guild_id)
        channel = guild.get_channel(channel_id) if guild else self.bot.get_channel(channel_id)
        if not channel:
            return
        try:
            kwargs = {"allowed_mentions": discord.AllowedMentions.none()}
            if content:
                kwargs["content"] = _clean_text(content, 1900)
            if embed:
                kwargs["embed"] = embed
            await channel.send(**kwargs)
        except (discord.Forbidden, discord.HTTPException):
            return


async def setup(bot):
    await bot.add_cog(MinecraftBridge(bot))
