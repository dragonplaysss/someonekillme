from __future__ import annotations

import asyncio
from dataclasses import dataclass
import os
from pathlib import Path
import re

import discord
from discord.ext import commands

from cogs.server_config import get_channel_id, get_guild_config, is_admin, is_mod
from cogs.trigger_parser import parse_shorekeeper_trigger

try:
    import wavelink
except ImportError:
    wavelink = None

try:
    import yt_dlp
except ImportError:
    yt_dlp = None


LAVALINK_URI = os.getenv("LAVALINK_URI", "http://127.0.0.1:2333")
LAVALINK_PASSWORD = os.getenv("LAVALINK_PASSWORD", "youshallnotpass")
MUSIC_SEARCH_PROVIDER = os.getenv("MUSIC_SEARCH_PROVIDER", "soundcloud").lower()
YTDLP_COOKIES_FILE = os.getenv("YTDLP_COOKIES_FILE")

URL_RE = re.compile(r"https?://", re.IGNORECASE)
YOUTUBE_URL_RE = re.compile(
    r"https?://(?:www\.|m\.|music\.)?(?:youtube\.com|youtu\.be)/",
    re.IGNORECASE,
)
track_metadata: dict[str, dict] = {}


@dataclass(frozen=True)
class SearchAttempt:
    label: str
    source: object | None
    kind: str


class QuietYtdlpLogger:
    def debug(self, message):
        pass

    def warning(self, message):
        pass

    def error(self, message):
        pass


def is_url(query: str) -> bool:
    return bool(URL_RE.match(query.strip()))


def is_youtube_url(query: str) -> bool:
    return bool(YOUTUBE_URL_RE.match(query.strip()))


def track_key(track):
    return getattr(track, "encoded", None) or getattr(track, "identifier", None)


def save_track_metadata(track, **metadata):
    key = track_key(track)
    if not key:
        return

    current = track_metadata.setdefault(key, {})
    current.update(metadata)


def get_track_metadata(track):
    return track_metadata.get(track_key(track), {})


def track_title(track):
    metadata = get_track_metadata(track)
    return metadata.get("title") or getattr(track, "title", "Unknown")


def track_artwork(track):
    metadata = get_track_metadata(track)
    return metadata.get("artwork") or getattr(track, "artwork", None)


def format_duration(milliseconds):
    if not milliseconds:
        return "Live"

    seconds = int(milliseconds // 1000)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)

    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


def track_duration(track):
    metadata = get_track_metadata(track)
    return format_duration(metadata.get("duration_ms") or getattr(track, "length", 0))


def readable_error(error) -> str:
    text = re.sub(r"\x1b\[[0-9;]*m", "", str(error)).strip()
    if len(text) > 350:
        text = f"{text[:347]}..."
    return text or type(error).__name__


def ytdlp_cookie_status() -> str:
    if yt_dlp is None:
        return "[YTDLP] fallback disabled: yt-dlp is not installed."

    if not YTDLP_COOKIES_FILE:
        return "[YTDLP] cookies not configured; fallback will run without cookies."

    path = Path(YTDLP_COOKIES_FILE).expanduser().resolve()
    if not path.exists():
        return f"[YTDLP] cookies configured but missing: {path}"
    if path.stat().st_size == 0:
        return f"[YTDLP] cookies configured but empty: {path}"

    youtube_lines = 0
    header_ok = False

    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for index, line in enumerate(handle):
                if index == 0 and (
                    line.startswith("# Netscape HTTP Cookie File")
                    or line.startswith("# HTTP Cookie File")
                ):
                    header_ok = True
                if "youtube.com" in line or "youtu.be" in line:
                    youtube_lines += 1
    except OSError as exc:
        return f"[YTDLP] cookies configured but unreadable: {path} ({exc})"

    if not header_ok:
        return f"[YTDLP] cookies file found but header is not Netscape format: {path}"

    return (
        f"[YTDLP] cookies loaded for fallback: {path} "
        f"({youtube_lines} YouTube cookie lines, {path.stat().st_size} bytes)"
    )


def ytdlp_options():
    options = {
        "format": "bestaudio[acodec=opus]/bestaudio/best",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "socket_timeout": 15,
        "retries": 2,
        "extractor_retries": 2,
        "source_address": os.getenv("YTDLP_SOURCE_ADDRESS", "0.0.0.0"),
        "logger": QuietYtdlpLogger(),
        "extractor_args": {
            "youtube": {
                "player_client": ["web", "mweb"],
            }
        },
    }

    if YTDLP_COOKIES_FILE:
        options["cookiefile"] = str(Path(YTDLP_COOKIES_FILE).expanduser().resolve())

    return options


def extract_ytdlp_info(query: str):
    if yt_dlp is None:
        raise RuntimeError("yt-dlp is not installed.")

    identifier = query if is_url(query) else f"ytsearch1:{query}"

    with yt_dlp.YoutubeDL(ytdlp_options()) as ytdl:
        data = ytdl.extract_info(identifier, download=False)

    entries = data.get("entries") if isinstance(data, dict) else None
    if entries is not None:
        data = next((entry for entry in entries if entry), None)

    if not data:
        raise ValueError("yt-dlp found no playable result.")

    stream_url = data.get("url")
    if not stream_url:
        formats = data.get("formats") or []
        playable_formats = [
            item
            for item in formats
            if item.get("url") and item.get("acodec") not in {None, "none"}
        ]
        if playable_formats:
            stream_url = playable_formats[-1]["url"]

    if not stream_url:
        raise ValueError("yt-dlp did not return a direct audio stream.")

    duration = data.get("duration") or 0
    return {
        "stream_url": stream_url,
        "title": data.get("title") or "Unknown",
        "duration_ms": int(duration * 1000),
        "artwork": data.get("thumbnail"),
        "webpage_url": data.get("webpage_url") or data.get("original_url"),
    }


class WavelinkMusicControls(discord.ui.View):
    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot

    async def can_control(self, interaction):
        player = interaction.guild.voice_client if interaction.guild else None
        if not player or not getattr(player, "current", None):
            await interaction.response.send_message("Nothing is playing.", ephemeral=True)
            return None

        current = player.current
        requester_id = get_track_metadata(current).get("requester_id")
        cfg = get_guild_config(interaction.guild.id)
        skip_role_id = cfg.get("skip_role")
        has_skip_role = skip_role_id and any(
            role.id == skip_role_id for role in interaction.user.roles
        )

        if interaction.user.id == requester_id or has_skip_role or is_mod(interaction.user):
            return player

        await interaction.response.send_message("No permission.", ephemeral=True)
        return None

    @discord.ui.button(label="Skip", style=discord.ButtonStyle.danger)
    async def skip(self, interaction: discord.Interaction, button: discord.ui.Button):
        player = await self.can_control(interaction)
        if not player:
            return
        await player.skip()
        await interaction.response.send_message("Skipped.")

    @discord.ui.button(label="Pause", style=discord.ButtonStyle.secondary)
    async def pause(self, interaction: discord.Interaction, button: discord.ui.Button):
        player = await self.can_control(interaction)
        if not player:
            return
        await player.pause(True)
        await interaction.response.send_message("Paused.")

    @discord.ui.button(label="Resume", style=discord.ButtonStyle.success)
    async def resume(self, interaction: discord.Interaction, button: discord.ui.Button):
        player = await self.can_control(interaction)
        if not player:
            return
        await player.pause(False)
        await interaction.response.send_message("Resumed.")

    @discord.ui.button(label="Loop", style=discord.ButtonStyle.primary)
    async def loop(self, interaction: discord.Interaction, button: discord.ui.Button):
        player = await self.can_control(interaction)
        if not player:
            return
        player.shorekeeper_loop = not getattr(player, "shorekeeper_loop", False)
        await interaction.response.send_message(
            f"Loop is now {'ON' if player.shorekeeper_loop else 'OFF'}."
        )

    @discord.ui.button(label="Stop", style=discord.ButtonStyle.danger)
    async def stop(self, interaction: discord.Interaction, button: discord.ui.Button):
        player = await self.can_control(interaction)
        if not player:
            return
        player.queue.clear()
        player.shorekeeper_loop = False
        player.shorekeeper_stopping = True
        await player.disconnect()
        try:
            await interaction.message.delete()
        except Exception:
            pass
        await interaction.response.send_message("Stopped.")


class WavelinkMusic(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.node_ready = False
        self._node_lock = asyncio.Lock()

    async def cog_load(self):
        print(
            "[MUSIC] Backend=wavelink; search order=SoundCloud, YouTube Music, "
            f"YouTube; configured provider={MUSIC_SEARCH_PROVIDER}; "
            "yt-dlp rescue=enabled"
        )
        print(ytdlp_cookie_status())
        await self.connect_lavalink(silent=True)

    async def connect_lavalink(self, silent=False):
        if wavelink is None:
            return False

        async with self._node_lock:
            try:
                wavelink.Pool.get_node()
                self.node_ready = True
                return True
            except Exception:
                pass

            try:
                node = wavelink.Node(
                    identifier="shorekeeper",
                    uri=LAVALINK_URI,
                    password=LAVALINK_PASSWORD,
                )
                await wavelink.Pool.connect(nodes=[node], client=self.bot)
                self.node_ready = True
                return True
            except Exception as exc:
                self.node_ready = False
                if not silent:
                    print(f"[WAVELINK NODE ERROR] {type(exc).__name__}: {exc}")
                return False

    @commands.Cog.listener()
    async def on_wavelink_node_ready(self, payload):
        self.node_ready = True
        print(f"[WAVELINK] Node ready: {payload.node.identifier}")

    @commands.Cog.listener()
    async def on_wavelink_track_end(self, payload):
        player = payload.player
        if not player:
            return

        reason = str(getattr(payload, "reason", "")).lower()
        if reason in {"replaced", "stopped", "cleanup", "load_failed"}:
            return

        if getattr(player, "shorekeeper_stopping", False):
            return

        if getattr(player, "shorekeeper_loop", False) and payload.track:
            await self.play_raw(player, payload.track)
            return

        await self.play_next_queued(player)

    @commands.Cog.listener()
    async def on_wavelink_track_start(self, payload):
        player = payload.player
        track = payload.track
        if not player or not track:
            return

        await self.update_panel(player.guild.id)
        await self.announce_now_playing(player, track)

    @commands.Cog.listener()
    async def on_wavelink_track_exception(self, payload):
        player = payload.player
        if not player:
            return

        exception = getattr(payload, "exception", None)
        print(
            "[WAVELINK PLAYBACK ERROR] "
            f"{track_title(payload.track)}: {readable_error(exception)}"
        )
        await self.recover_from_failure(player, payload.track, exception)

    def get_author_voice_channel(self, message):
        if not message.author.voice or not message.author.voice.channel:
            return None
        return message.author.voice.channel

    async def ensure_node(self, channel):
        if self.node_ready:
            return True

        if await self.connect_lavalink():
            return True

        await channel.send(
            "Music backend is not connected to Lavalink yet. "
            "Start or restart the Lavalink service, then try again."
        )
        return False

    async def ensure_connected(self, message):
        voice_channel = self.get_author_voice_channel(message)
        if not voice_channel:
            await message.channel.send("Join a voice channel first.")
            return None

        player = message.guild.voice_client
        if player and player.channel.id != voice_channel.id:
            await message.channel.send(f"I am already playing in {player.channel.mention}.")
            return None

        if player:
            self.prepare_player(player, message.channel.id)
            return player

        try:
            player = await voice_channel.connect(cls=wavelink.Player, self_deaf=True)
            self.prepare_player(player, message.channel.id)
            return player
        except Exception as exc:
            print(f"[WAVELINK VOICE ERROR] {type(exc).__name__}: {exc}")
            await message.channel.send(
                f"Voice connect failed: {type(exc).__name__}: {exc}"
            )
            return None

    def prepare_player(self, player, text_channel_id):
        player.shorekeeper_text_channel_id = text_channel_id
        player.shorekeeper_loop = getattr(player, "shorekeeper_loop", False)
        player.shorekeeper_stopping = False
        player.shorekeeper_volume = getattr(player, "shorekeeper_volume", 50)

        if wavelink is not None:
            player.autoplay = wavelink.AutoPlayMode.disabled

    def search_attempts(self, query: str):
        if is_url(query):
            kind = "direct_youtube" if is_youtube_url(query) else "direct"
            return [SearchAttempt("direct URL", None, kind)]

        return [
            SearchAttempt("SoundCloud", wavelink.TrackSource.SoundCloud, "soundcloud"),
            SearchAttempt("YouTube Music", wavelink.TrackSource.YouTubeMusic, "youtube"),
            SearchAttempt("YouTube", wavelink.TrackSource.YouTube, "youtube"),
        ]

    async def search_one(self, query: str, attempt: SearchAttempt):
        results = await wavelink.Playable.search(query, source=attempt.source)
        tracks = list(results)

        for track in tracks:
            if getattr(track, "is_preview", False):
                continue
            return track

        return None

    async def search_tracks(self, query, requester, status_message=None):
        errors = []

        for attempt in self.search_attempts(query):
            if status_message:
                await status_message.edit(
                    content=f"Searching {attempt.label}: **{query}**"
                )

            try:
                track = await self.search_one(query, attempt)
            except Exception as exc:
                errors.append(f"{attempt.label}: {type(exc).__name__}: {exc}")
                print(
                    f"[WAVELINK SEARCH ERROR] {attempt.label}: "
                    f"{type(exc).__name__}: {exc}"
                )
                track = None

            if not track:
                continue

            save_track_metadata(
                track,
                requester_id=requester.id,
                requester=requester.mention,
                original_query=query,
                source_kind=attempt.kind,
                source_label=attempt.label,
                fallback_attempts=(),
            )
            return track

        try:
            return await self.resolve_ytdlp_track(
                query,
                requester_id=requester.id,
                requester=requester.mention,
                fallback_attempts=("soundcloud", "youtube", "yt-dlp"),
            )
        except Exception as exc:
            errors.append(f"yt-dlp: {type(exc).__name__}: {exc}")
            print(f"[YTDLP RESCUE ERROR] {type(exc).__name__}: {exc}")

        detail = "; ".join(errors[-3:])
        if detail:
            raise ValueError(f"No playable results found. Last errors: {detail}")
        raise ValueError("No playable results found.")

    async def search_youtube_fallback(self, query, base_metadata):
        errors = []
        attempts = (
            SearchAttempt("YouTube Music", wavelink.TrackSource.YouTubeMusic, "youtube"),
            SearchAttempt("YouTube", wavelink.TrackSource.YouTube, "youtube"),
        )

        for attempt in attempts:
            try:
                track = await self.search_one(query, attempt)
            except Exception as exc:
                errors.append(f"{attempt.label}: {type(exc).__name__}: {exc}")
                print(
                    f"[WAVELINK FALLBACK SEARCH ERROR] {attempt.label}: "
                    f"{type(exc).__name__}: {exc}"
                )
                continue

            if not track:
                continue

            attempted = tuple(
                dict.fromkeys((*base_metadata.get("fallback_attempts", ()), "youtube"))
            )
            save_track_metadata(
                track,
                requester_id=base_metadata.get("requester_id"),
                requester=base_metadata.get("requester"),
                guild_id=base_metadata.get("guild_id"),
                original_query=query,
                source_kind="youtube",
                source_label=attempt.label,
                fallback_attempts=attempted,
            )
            return track

        detail = "; ".join(errors[-2:])
        raise ValueError(detail or "YouTube fallback returned no results.")

    async def resolve_ytdlp_track(
        self,
        query,
        *,
        requester_id=None,
        requester=None,
        guild_id=None,
        fallback_attempts=(),
    ):
        loop = asyncio.get_running_loop()
        info = await loop.run_in_executor(None, lambda: extract_ytdlp_info(query))
        results = await wavelink.Playable.search(info["stream_url"], source=None)
        tracks = list(results)

        if not tracks:
            raise ValueError("Lavalink could not load the yt-dlp direct stream.")

        track = tracks[0]
        save_track_metadata(
            track,
            requester_id=requester_id,
            requester=requester,
            guild_id=guild_id,
            original_query=query,
            source_kind="yt-dlp",
            source_label="yt-dlp direct stream",
            fallback_attempts=tuple(dict.fromkeys((*fallback_attempts, "yt-dlp"))),
            title=info["title"],
            duration_ms=info["duration_ms"],
            artwork=info["artwork"],
            webpage_url=info["webpage_url"],
        )
        return track

    async def build_next_fallback(self, player, failed_track, reason):
        metadata = dict(get_track_metadata(failed_track))
        query = metadata.get("original_query") or getattr(failed_track, "uri", None)
        if not query:
            return None

        attempted = set(metadata.get("fallback_attempts", ()))
        source_kind = metadata.get("source_kind")

        if source_kind == "soundcloud" and "youtube" not in attempted:
            attempted.add("youtube")
            metadata["fallback_attempts"] = tuple(attempted)
            await self.send_or_edit_status(
                player,
                "SoundCloud playback failed. Trying YouTube fallback...",
            )
            try:
                return await self.search_youtube_fallback(query, metadata)
            except Exception as exc:
                print(f"[YOUTUBE FALLBACK ERROR] {type(exc).__name__}: {exc}")

        if "yt-dlp" not in attempted and yt_dlp is not None:
            attempted.add("yt-dlp")
            await self.send_or_edit_status(
                player,
                "Lavalink playback failed. Trying yt-dlp direct stream...",
            )
            try:
                return await self.resolve_ytdlp_track(
                    query,
                    requester_id=metadata.get("requester_id"),
                    requester=metadata.get("requester"),
                    guild_id=metadata.get("guild_id") or player.guild.id,
                    fallback_attempts=tuple(attempted),
                )
            except Exception as exc:
                print(f"[YTDLP FALLBACK ERROR] {type(exc).__name__}: {exc}")

        if yt_dlp is None:
            print("[YTDLP FALLBACK ERROR] yt-dlp is not installed.")

        return None

    async def play_raw(self, player, track):
        await player.play(
            track,
            volume=getattr(player, "shorekeeper_volume", 50),
            populate=False,
        )

    async def recover_from_failure(self, player, failed_track, reason):
        current = failed_track

        for _ in range(3):
            fallback = await self.build_next_fallback(player, current, reason)
            if not fallback:
                break

            try:
                await self.play_raw(player, fallback)
                return True
            except Exception as exc:
                print(
                    f"[WAVELINK FALLBACK PLAY ERROR] {track_title(fallback)}: "
                    f"{type(exc).__name__}: {exc}"
                )
                current = fallback
                reason = exc

        if await self.play_next_queued(player):
            return False

        await self.send_or_edit_status(
            player,
            "Playback failed. No SoundCloud, YouTube, or yt-dlp fallback was playable.",
        )
        await self.update_panel(player.guild.id)

        try:
            await player.disconnect()
        except Exception:
            pass

        return False

    async def play_next_queued(self, player):
        if getattr(player, "shorekeeper_stopping", False):
            return False

        if player.queue:
            next_track = player.queue.get()
            await self.send_or_edit_status(
                player,
                f"Loading next queued track: **{track_title(next_track)}**",
            )
            try:
                await self.play_raw(player, next_track)
            except Exception as exc:
                await self.recover_from_failure(player, next_track, exc)
            return True

        await self.update_panel(player.guild.id)
        return False

    async def get_status_message(self, player):
        channel_id = getattr(player, "shorekeeper_text_channel_id", None)
        message_id = getattr(player, "shorekeeper_status_message_id", None)
        channel = player.guild.get_channel(channel_id) if channel_id else None
        if not channel or not message_id:
            return None

        try:
            return await channel.fetch_message(message_id)
        except Exception:
            return None

    async def send_or_edit_status(self, player, content):
        channel_id = getattr(player, "shorekeeper_text_channel_id", None)
        channel = player.guild.get_channel(channel_id) if channel_id else None
        if not channel:
            return None

        content = content[:1900]
        status_message = await self.get_status_message(player)
        if status_message:
            try:
                await status_message.edit(content=content)
                return status_message
            except Exception:
                pass

        status_message = await channel.send(content)
        player.shorekeeper_status_message_id = status_message.id
        return status_message

    async def clear_status_message(self, player):
        status_message = await self.get_status_message(player)
        player.shorekeeper_status_message_id = None
        if status_message:
            try:
                await status_message.delete()
            except Exception:
                pass

    async def clear_now_playing_message(self, player):
        channel_id = getattr(player, "shorekeeper_text_channel_id", None)
        message_id = getattr(player, "shorekeeper_now_playing_message_id", None)
        channel = player.guild.get_channel(channel_id) if channel_id else None
        player.shorekeeper_now_playing_message_id = None

        if not channel or not message_id:
            return

        try:
            message = await channel.fetch_message(message_id)
            await message.delete()
        except Exception:
            pass

    async def update_panel(self, guild_id):
        cfg = get_guild_config(guild_id).get("music", {})
        webhook = cfg.get("webhook_url")
        msg_id = cfg.get("message_id")
        if not webhook or not msg_id:
            return

        guild = self.bot.get_guild(guild_id)
        player = guild.voice_client if guild else None
        current = getattr(player, "current", None) if player else None
        description = f"**{track_title(current)}**" if current else "Idle"

        data = {
            "embeds": [
                {
                    "title": "Music Player",
                    "description": description,
                    "color": 0x5865F2,
                }
            ]
        }

        import aiohttp

        async with aiohttp.ClientSession() as session:
            await session.patch(f"{webhook}/messages/{msg_id}", json=data)

    async def announce_now_playing(self, player, track):
        channel_id = getattr(player, "shorekeeper_text_channel_id", None)
        channel = player.guild.get_channel(channel_id) if channel_id else None
        if not channel:
            return

        key = track_key(track)
        if getattr(player, "shorekeeper_last_announced_key", None) == key:
            await self.clear_status_message(player)
            return

        player.shorekeeper_last_announced_key = key
        await self.clear_status_message(player)
        await self.clear_now_playing_message(player)

        requester = get_track_metadata(track).get("requester", "Unknown")
        embed = discord.Embed(
            title="Now Playing",
            description=f"**{track_title(track)}**",
            color=0x5865F2,
        )
        embed.add_field(name="Duration", value=track_duration(track))
        embed.add_field(name="Requested By", value=requester)

        source_label = get_track_metadata(track).get("source_label")
        if source_label:
            embed.set_footer(text=f"Source: {source_label}")

        artwork = track_artwork(track)
        if artwork:
            embed.set_thumbnail(url=artwork)

        message = await channel.send(embed=embed, view=WavelinkMusicControls(self.bot))
        player.shorekeeper_now_playing_message_id = message.id

    async def command_play(self, message, query):
        music_channel_id = get_channel_id(message.guild.id, "music")
        if music_channel_id and message.channel.id != music_channel_id:
            return

        if not await self.ensure_node(message.channel):
            return

        status_message = await message.channel.send(f"Searching: **{query}**")

        try:
            track = await self.search_tracks(query, message.author, status_message)
        except Exception as exc:
            print(f"[MUSIC SEARCH FAILED] {type(exc).__name__}: {exc}")
            return await status_message.edit(
                content=f"Search failed: {type(exc).__name__}: {readable_error(exc)}"
            )

        player = await self.ensure_connected(message)
        if not player:
            return await status_message.edit(content="Voice connection failed.")

        self.prepare_player(player, message.channel.id)
        player.shorekeeper_status_message_id = status_message.id

        save_track_metadata(
            track,
            guild_id=message.guild.id,
            text_channel_id=message.channel.id,
        )

        if not player.playing and not player.paused:
            await status_message.edit(content=f"Loading: **{track_title(track)}**")
            try:
                await self.play_raw(player, track)
            except Exception as exc:
                await self.recover_from_failure(player, track, exc)
        else:
            player.queue.put(track)
            await status_message.edit(content=f"Queued: **{track_title(track)}**")
            await self.update_panel(message.guild.id)

    async def command_skip(self, message):
        player = message.guild.voice_client
        if not player or not player.current:
            return await message.channel.send("Nothing is playing.")

        requester_id = get_track_metadata(player.current).get("requester_id")
        if message.author.id != requester_id and not is_mod(message.author):
            return await message.channel.send("Only the requester or mods can skip.")

        await player.skip()
        await message.channel.send("Skipped.")

    async def command_pause(self, message):
        player = message.guild.voice_client
        if player and player.playing:
            await player.pause(True)
            return await message.channel.send("Paused.")
        await message.channel.send("Nothing is playing.")

    async def command_resume(self, message):
        player = message.guild.voice_client
        if player and player.paused:
            await player.pause(False)
            return await message.channel.send("Resumed.")
        await message.channel.send("Nothing is paused.")

    async def command_stop(self, message):
        player = message.guild.voice_client
        if player:
            player.queue.clear()
            player.shorekeeper_loop = False
            player.shorekeeper_stopping = True
            await self.clear_now_playing_message(player)
            await player.disconnect()
        await self.update_panel(message.guild.id)
        await message.channel.send("Stopped.")

    async def command_queue(self, message):
        player = message.guild.voice_client
        if not player:
            return await message.channel.send("Join a voice channel first.")

        embed = discord.Embed(title="Music Queue", color=0x5865F2)
        if player.current:
            embed.add_field(
                name="Now Playing",
                value=f"**{track_title(player.current)}**",
                inline=False,
            )

        if player.queue:
            tracks = list(player.queue)[:10]
            embed.add_field(
                name="Up Next",
                value="\n".join(
                    f"`{index + 1}` - {track_title(track)}"
                    for index, track in enumerate(tracks)
                ),
                inline=False,
            )
        else:
            embed.add_field(name="Up Next", value="Queue is empty.", inline=False)

        embed.set_footer(text=f"{len(player.queue)} songs queued")
        await message.channel.send(embed=embed)

    async def command_nowplaying(self, message):
        player = message.guild.voice_client
        if not player or not player.current:
            return await message.channel.send("Nothing is playing.")
        await message.channel.send(f"Now playing: **{track_title(player.current)}**")

    async def command_loop(self, message):
        player = message.guild.voice_client
        if not player:
            return await message.channel.send("Join a voice channel first.")
        player.shorekeeper_loop = not getattr(player, "shorekeeper_loop", False)
        await message.channel.send(f"Loop is now {'ON' if player.shorekeeper_loop else 'OFF'}.")

    async def command_volume(self, message, value):
        if not is_admin(message.author):
            return await message.channel.send("Only admins can change volume.")

        player = message.guild.voice_client
        if not player:
            return await message.channel.send("Join a voice channel first.")

        try:
            amount = max(0, min(100, int(value)))
        except ValueError:
            return await message.channel.send("Volume must be 0-100.")

        player.shorekeeper_volume = amount
        await player.set_volume(amount)
        await message.channel.send(f"Volume set to {amount}%.")

    @commands.Cog.listener()
    async def on_message(self, message):
        try:
            trigger = parse_shorekeeper_trigger(self.bot, message)
            if not trigger:
                return

            keyword = trigger["keyword"]
            query = trigger["extra"] or " ".join(trigger["args"])

            if keyword == "play":
                if not query:
                    return await message.channel.send("Use `@shorekeeper play ; song name`.")
                return await self.command_play(message, query)
            if keyword == "skip":
                return await self.command_skip(message)
            if keyword == "pause":
                return await self.command_pause(message)
            if keyword == "resume":
                return await self.command_resume(message)
            if keyword == "stop":
                return await self.command_stop(message)
            if keyword == "queue":
                return await self.command_queue(message)
            if keyword in {"nowplaying", "np"}:
                return await self.command_nowplaying(message)
            if keyword == "loop":
                return await self.command_loop(message)
            if keyword == "volume":
                return await self.command_volume(message, query)
        except Exception as exc:
            print(f"[WAVELINK COMMAND ERROR] {type(exc).__name__}: {exc}")
            await message.channel.send(
                f"Music command failed: {type(exc).__name__}: {exc}"
            )


async def setup(bot):
    if os.getenv("MUSIC_BACKEND", "wavelink").lower() != "wavelink":
        print("[SKIPPED] cogs.music.wavelink_player: MUSIC_BACKEND is not wavelink")
        return

    if wavelink is None:
        raise RuntimeError(
            "wavelink is not installed. Run `python -m pip install -r requirements.txt`."
        )

    await bot.add_cog(WavelinkMusic(bot))
