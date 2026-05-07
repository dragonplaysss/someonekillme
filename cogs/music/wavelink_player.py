from __future__ import annotations

import asyncio
from dataclasses import dataclass
import logging
import os
from pathlib import Path
import re
import shutil

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
YTDLP_SOURCE_ADDRESS = os.getenv("YTDLP_SOURCE_ADDRESS", "0.0.0.0")
YTDLP_TIMEOUT = int(os.getenv("YTDLP_TIMEOUT", "35"))
YTDLP_EXECUTABLE = os.getenv("YTDLP_EXECUTABLE", "yt-dlp")
MAX_TRACK_RECOVERY_ATTEMPTS = int(os.getenv("MUSIC_MAX_RECOVERY_ATTEMPTS", "5"))
MAX_NODE_CONNECT_ATTEMPTS = int(os.getenv("MUSIC_NODE_CONNECT_ATTEMPTS", "3"))
LOG = logging.getLogger("shorekeeper.music")

URL_RE = re.compile(r"https?://", re.IGNORECASE)
YOUTUBE_URL_RE = re.compile(
    r"https?://(?:www\.|m\.|music\.)?(?:youtube\.com|youtu\.be)/",
    re.IGNORECASE,
)
track_metadata: dict[str, dict] = {}


logging.basicConfig(
    level=os.getenv("MUSIC_LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)


@dataclass(frozen=True)
class SearchAttempt:
    label: str
    source: object | None
    kind: str
    prefix: str | None = None


class QuietYtdlpLogger:
    def debug(self, message):
        pass

    def warning(self, message):
        pass

    def error(self, message):
        LOG.debug("[yt-dlp] %s", message)


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


def track_uri(track) -> str:
    return (
        getattr(track, "uri", None)
        or getattr(getattr(track, "info", None), "uri", None)
        or ""
    )


def track_identifier(track) -> str:
    return (
        getattr(track, "identifier", None)
        or getattr(getattr(track, "info", None), "identifier", None)
        or ""
    )


def is_soundcloud_preview(track) -> bool:
    if getattr(track, "is_preview", False):
        return True

    text = f"{track_uri(track)} {track_identifier(track)}".lower()
    return "/preview/" in text or "preview/hls" in text


def is_soundcloud_track(track) -> bool:
    metadata = get_track_metadata(track)
    source = (
        metadata.get("source_kind")
        or metadata.get("source_label")
        or getattr(track, "source", None)
        or getattr(track, "source_name", None)
        or getattr(getattr(track, "info", None), "source_name", None)
        or ""
    )
    return "soundcloud" in str(source).lower()


def should_recover_early_end(player, track, reason: str) -> bool:
    if not track or not is_soundcloud_track(track):
        return False

    if reason not in {"finished", "stopped"}:
        return False

    length = get_track_metadata(track).get("duration_ms") or getattr(track, "length", 0) or 0
    position = getattr(player, "position", 0) or 0

    if not length or length < 90_000:
        return False

    remaining = length - position
    return position < (length * 0.75) and remaining > 45_000


def queue_size(player) -> int:
    queue = getattr(player, "queue", None)
    if queue is None:
        return 0

    try:
        return len(queue)
    except Exception:
        return 0


def queue_empty(player) -> bool:
    queue = getattr(player, "queue", None)
    if queue is None:
        return True

    is_empty = getattr(queue, "is_empty", None)
    if callable(is_empty):
        try:
            return bool(is_empty())
        except Exception:
            pass
    if isinstance(is_empty, bool):
        return is_empty

    return queue_size(player) == 0


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
    auth_cookies = 0
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
                    if any(name in line for name in ("\tSAPISID\t", "\tHSID\t", "\tSID\t", "\tLOGIN_INFO\t")):
                        auth_cookies += 1
    except OSError as exc:
        return f"[YTDLP] cookies configured but unreadable: {path} ({exc})"

    if not header_ok:
        return f"[YTDLP] cookies file found but header is not Netscape format: {path}"

    if youtube_lines == 0:
        return f"[YTDLP] cookies file has no YouTube cookies: {path}"

    if auth_cookies == 0:
        return (
            f"[YTDLP] cookies file loads but has no obvious YouTube auth cookies: {path}. "
            "Age/bot-gated videos may still fail."
        )

    return (
        f"[YTDLP] cookies loaded for fallback: {path} "
        f"({youtube_lines} YouTube cookie lines, {auth_cookies} auth-looking cookies, "
        f"{path.stat().st_size} bytes)"
    )


def ytdlp_options(profile: str = "web"):
    clients = {
        "web": ["web", "mweb"],
        "tv": ["tv", "web"],
        "ios": ["ios", "web"],
        "android": ["android", "web"],
    }.get(profile, ["web", "mweb"])

    options = {
        "format": (
            "bestaudio[acodec=opus][protocol^=http]/"
            "bestaudio[ext=m4a][protocol^=http]/"
            "bestaudio[protocol^=http]/bestaudio/best"
        ),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "socket_timeout": 20,
        "retries": 5,
        "fragment_retries": 5,
        "extractor_retries": 4,
        "file_access_retries": 3,
        "source_address": YTDLP_SOURCE_ADDRESS,
        "cachedir": False,
        "geo_bypass": True,
        "http_chunk_size": 10485760,
        "remote_components": ["ejs:github"],
        "logger": QuietYtdlpLogger(),
        "extractor_args": {
            "youtube": {
                "player_client": clients,
            }
        },
    }

    if YTDLP_COOKIES_FILE:
        options["cookiefile"] = str(Path(YTDLP_COOKIES_FILE).expanduser().resolve())

    return options


def select_stream_url(data: dict) -> str | None:
    stream_url = data.get("url")
    if stream_url:
        return stream_url

    formats = data.get("formats") or []
    playable_formats = [
        item
        for item in formats
        if item.get("url")
        and item.get("acodec") not in {None, "none"}
        and item.get("protocol") not in {"mhtml"}
    ]
    if not playable_formats:
        return None

    def score(item):
        protocol = item.get("protocol") or ""
        ext = item.get("ext") or ""
        abr = item.get("abr") or 0
        return (
            3 if protocol.startswith("https") else 2 if protocol.startswith("http") else 1,
            2 if ext in {"webm", "m4a", "mp4"} else 1,
            abr,
        )

    return sorted(playable_formats, key=score)[-1]["url"]


def extract_ytdlp_info_once(query: str, profile: str, search_prefix: str | None = None):
    if yt_dlp is None:
        raise RuntimeError("yt-dlp is not installed.")

    if is_url(query):
        identifier = query
    else:
        identifier = f"{search_prefix or 'ytsearch1'}:{query}"

    LOG.info("[YTDLP] extracting via profile=%s identifier=%s", profile, identifier)
    options = ytdlp_options(profile)
    LOG.info("YTDLP FINAL OPTIONS: %s", options)
    with yt_dlp.YoutubeDL(options) as ytdl:
        data = ytdl.extract_info(identifier, download=False)

    entries = data.get("entries") if isinstance(data, dict) else None
    if entries is not None:
        data = next((entry for entry in entries if entry), None)

    if not data:
        raise ValueError("yt-dlp found no playable result.")

    stream_url = select_stream_url(data)

    if not stream_url:
        raise ValueError("yt-dlp did not return a direct audio stream.")

    duration = data.get("duration") or 0
    return {
        "stream_url": stream_url,
        "title": data.get("title") or "Unknown",
        "duration_ms": int(duration * 1000),
        "artwork": data.get("thumbnail"),
        "webpage_url": data.get("webpage_url") or data.get("original_url"),
        "profile": profile,
    }


def extract_ytdlp_info(query: str):
    errors = []
    profiles = ("web", "tv", "ios", "android")
    search_prefixes = (None, "ytsearch1") if is_url(query) else ("ytsearch1", "ytmsearch1")

    for search_prefix in search_prefixes:
        for profile in profiles:
            try:
                return extract_ytdlp_info_once(query, profile, search_prefix)
            except Exception as exc:
                errors.append(f"{profile}/{search_prefix or 'direct'}: {type(exc).__name__}: {exc}")
                LOG.warning(
                    "[YTDLP] extraction failed profile=%s prefix=%s error=%s: %s",
                    profile,
                    search_prefix or "direct",
                    type(exc).__name__,
                    readable_error(exc),
                )

    raise ValueError("yt-dlp exhausted all extraction profiles: " + "; ".join(errors[-4:]))


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

        cog = self.bot.get_cog("WavelinkMusic")
        if cog and hasattr(cog, "skip_player"):
            await cog.skip_player(player, requested_by=interaction.user)
        else:
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
        self._watchdog_task = None

    async def cog_load(self):
        LOG.info(
            "[MUSIC] Backend=wavelink; search order=SoundCloud, Spotify/LavaSrc, "
            "Apple Music/LavaSrc, Deezer/LavaSrc, yt-dlp rescue; "
            f"configured provider={MUSIC_SEARCH_PROVIDER}"
        )
        LOG.info(ytdlp_cookie_status())
        self.log_startup_validation()
        await self.connect_lavalink(silent=True)
        self._watchdog_task = asyncio.create_task(self.node_watchdog())

    async def cog_unload(self):
        if self._watchdog_task:
            self._watchdog_task.cancel()

    def log_startup_validation(self):
        if YTDLP_SOURCE_ADDRESS != "0.0.0.0":
            LOG.warning("[NETWORK] YTDLP_SOURCE_ADDRESS=%s; use 0.0.0.0 to force IPv4.", YTDLP_SOURCE_ADDRESS)
        else:
            LOG.info("[NETWORK] yt-dlp source_address=0.0.0.0 (IPv4 forced)")

        if yt_dlp is None:
            LOG.error("[YTDLP] Python package missing; install requirements.txt")
        else:
            LOG.info("[YTDLP] Python package available")

        if shutil.which(YTDLP_EXECUTABLE):
            LOG.info("[YTDLP] executable available: %s", YTDLP_EXECUTABLE)
        else:
            LOG.warning("[YTDLP] executable not found on PATH: %s; LavaSrc ytdlp source needs it.", YTDLP_EXECUTABLE)

        if shutil.which("deno"):
            LOG.info("[YTDLP] Deno JavaScript runtime available for YouTube EJS challenges")
        else:
            LOG.warning("[YTDLP] Deno not found; install Deno for reliable YouTube signature/n challenge solving.")

        try:
            import yt_dlp_ejs  # noqa: F401
            LOG.info("[YTDLP] yt-dlp-ejs package available")
        except Exception:
            LOG.warning("[YTDLP] yt-dlp-ejs package not available; remote EJS components will be used when needed.")

        if shutil.which("ffmpeg"):
            LOG.info("[FFMPEG] executable available")
        else:
            LOG.warning("[FFMPEG] executable not found; install ffmpeg on the VPS.")

    async def node_watchdog(self):
        await self.bot.wait_until_ready()
        while not self.bot.is_closed():
            try:
                await asyncio.sleep(30)
                if not self.node_ready:
                    await self.connect_lavalink(silent=True)
                    continue
                try:
                    node = wavelink.Pool.get_node()
                    LOG.debug("[WAVELINK] node healthy: %s", node.identifier)
                except Exception as exc:
                    self.node_ready = False
                    LOG.warning("[WAVELINK] node watchdog marked node unhealthy: %s", readable_error(exc))
                    await self.connect_lavalink(silent=True)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                LOG.warning("[WAVELINK] node watchdog error: %s", readable_error(exc))

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

            last_error = None
            for attempt in range(1, MAX_NODE_CONNECT_ATTEMPTS + 1):
                try:
                    LOG.info("[WAVELINK] connecting to Lavalink attempt=%s uri=%s", attempt, LAVALINK_URI)
                    node = wavelink.Node(
                        identifier="shorekeeper",
                        uri=LAVALINK_URI,
                        password=LAVALINK_PASSWORD,
                    )
                    await wavelink.Pool.connect(nodes=[node], client=self.bot)
                    self.node_ready = True
                    LOG.info("[WAVELINK] Lavalink connection established")
                    return True
                except Exception as exc:
                    last_error = exc
                    self.node_ready = False
                    LOG.warning("[WAVELINK NODE ERROR] attempt=%s %s: %s", attempt, type(exc).__name__, exc)
                    await asyncio.sleep(min(2 * attempt, 8))

            if not silent:
                LOG.error("[WAVELINK NODE ERROR] exhausted retries: %s", readable_error(last_error))
            return False

    @commands.Cog.listener()
    async def on_wavelink_node_ready(self, payload):
        self.node_ready = True
        LOG.info("[WAVELINK] Node ready: %s", payload.node.identifier)

    @commands.Cog.listener()
    async def on_wavelink_node_closed(self, payload):
        self.node_ready = False
        LOG.warning("[WAVELINK] Node closed: %s", payload)

    @commands.Cog.listener()
    async def on_wavelink_node_disconnected(self, payload):
        self.node_ready = False
        LOG.warning("[WAVELINK] Node disconnected: %s", payload)

    @commands.Cog.listener()
    async def on_wavelink_track_end(self, payload):
        player = payload.player
        if not player:
            return

        reason = str(getattr(payload, "reason", "")).lower()
        LOG.info(
            "[TRACK END] reason=%s track=%s queue_size=%s stopping=%s manual_skip=%s",
            reason or "unknown",
            track_title(payload.track),
            queue_size(player),
            getattr(player, "shorekeeper_stopping", False),
            getattr(player, "shorekeeper_manual_skip_active", False),
        )

        if reason in {"replaced", "cleanup", "load_failed"}:
            return

        if getattr(player, "shorekeeper_stopping", False):
            return

        if getattr(player, "shorekeeper_manual_skip_active", False):
            LOG.debug("[TRACK END] ignored because skip_player is already advancing")
            return

        if should_recover_early_end(player, payload.track, reason):
            LOG.warning(
                "[SOUNDCLOUD RECOVERY] early end detected title=%s position=%s length=%s reason=%s",
                track_title(payload.track),
                getattr(player, "position", None),
                getattr(payload.track, "length", None),
                reason,
            )
            await self.recover_from_failure(
                player,
                payload.track,
                RuntimeError(f"SoundCloud ended early with reason={reason}"),
            )
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
        LOG.warning("[WAVELINK PLAYBACK ERROR] %s: %s", track_title(payload.track), readable_error(exception))
        await self.recover_from_failure(player, payload.track, exception)

    @commands.Cog.listener()
    async def on_wavelink_track_stuck(self, payload):
        player = payload.player
        if not player:
            return

        threshold = getattr(payload, "threshold", None) or getattr(payload, "threshold_ms", None)
        LOG.warning(
            "[WAVELINK TRACK STUCK] title=%s source=%s position=%s threshold=%s queue_size=%s",
            track_title(payload.track),
            get_track_metadata(payload.track).get("source_label"),
            getattr(player, "position", None),
            threshold,
            queue_size(player),
        )
        await self.recover_from_failure(
            player,
            payload.track,
            RuntimeError(f"Track stuck at {getattr(player, 'position', None)}ms"),
        )

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

        last_error = None
        for attempt in range(1, 4):
            try:
                LOG.info("[VOICE] connecting guild=%s channel=%s attempt=%s", message.guild.id, voice_channel.id, attempt)
                player = await asyncio.wait_for(
                    voice_channel.connect(cls=wavelink.Player, self_deaf=True),
                    timeout=20,
                )
                self.prepare_player(player, message.channel.id)
                return player
            except Exception as exc:
                last_error = exc
                LOG.warning("[WAVELINK VOICE ERROR] attempt=%s %s: %s", attempt, type(exc).__name__, exc)
                await asyncio.sleep(min(2 * attempt, 6))

        await message.channel.send(
            f"Voice connect failed after retries: {type(last_error).__name__}: {last_error}"
        )
        return None

    def prepare_player(self, player, text_channel_id):
        player.shorekeeper_text_channel_id = text_channel_id
        player.shorekeeper_loop = getattr(player, "shorekeeper_loop", False)
        player.shorekeeper_stopping = False
        player.shorekeeper_volume = getattr(player, "shorekeeper_volume", 50)
        player.shorekeeper_manual_skip_active = getattr(
            player, "shorekeeper_manual_skip_active", False
        )

        if not hasattr(player, "shorekeeper_transition_lock"):
            player.shorekeeper_transition_lock = asyncio.Lock()

        if wavelink is not None:
            player.autoplay = wavelink.AutoPlayMode.disabled

    def search_attempts(self, query: str):
        if is_url(query):
            kind = "direct_youtube" if is_youtube_url(query) else "direct"
            return [SearchAttempt("direct URL", None, kind)]

        return [
            SearchAttempt("SoundCloud", wavelink.TrackSource.SoundCloud, "soundcloud"),
            SearchAttempt("Spotify/LavaSrc", "spsearch", "spotify", "spsearch"),
            SearchAttempt("Apple Music/LavaSrc", "amsearch", "applemusic", "amsearch"),
            SearchAttempt("Deezer/LavaSrc", "dzsearch", "deezer", "dzsearch"),
        ]

    async def search_one(self, query: str, attempt: SearchAttempt):
        LOG.info("[MUSIC RESOLVE] source=%s query=%s", attempt.label, query)
        results = await wavelink.Playable.search(query, source=attempt.source)
        tracks = list(results)

        for track in tracks:
            if is_soundcloud_preview(track):
                LOG.info(
                    "[MUSIC RESOLVE] rejected SoundCloud preview result title=%s uri=%s identifier=%s",
                    track_title(track),
                    track_uri(track),
                    track_identifier(track),
                )
                continue
            return track

        return None

    async def search_tracks(self, query, requester, status_message=None):
        errors = []

        attempts = self.search_attempts(query)
        if is_youtube_url(query):
            attempts = []

        for attempt in attempts:
            if status_message:
                await status_message.edit(
                    content=f"Searching {attempt.label}: **{query}**"
                )

            try:
                track = await self.search_one(query, attempt)
            except Exception as exc:
                errors.append(f"{attempt.label}: {type(exc).__name__}: {exc}")
                LOG.warning(
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
            if status_message:
                await status_message.edit(content=f"Searching yt-dlp rescue: **{query}**")
            return await self.resolve_ytdlp_track(
                query,
                requester_id=requester.id,
                requester=requester.mention,
                fallback_attempts=tuple(a.kind for a in attempts),
            )
        except Exception as exc:
            errors.append(f"yt-dlp: {type(exc).__name__}: {exc}")
            LOG.warning("[YTDLP RESCUE ERROR] %s: %s", type(exc).__name__, exc)

        detail = "; ".join(errors[-3:])
        if detail:
            raise ValueError(f"No playable results found. Last errors: {detail}")
        raise ValueError("No playable results found.")

    async def search_lavasrc_fallback(self, query, base_metadata):
        errors = []
        attempts = (
            SearchAttempt("Spotify/LavaSrc", "spsearch", "spotify", "spsearch"),
            SearchAttempt("Apple Music/LavaSrc", "amsearch", "applemusic", "amsearch"),
            SearchAttempt("Deezer/LavaSrc", "dzsearch", "deezer", "dzsearch"),
            SearchAttempt("SoundCloud", wavelink.TrackSource.SoundCloud, "soundcloud"),
        )

        for attempt in attempts:
            if attempt.kind in set(base_metadata.get("fallback_attempts", ())):
                continue

            try:
                track = await self.search_one(query, attempt)
            except Exception as exc:
                errors.append(f"{attempt.label}: {type(exc).__name__}: {exc}")
                LOG.warning("[WAVELINK FALLBACK SEARCH ERROR] %s: %s: %s", attempt.label, type(exc).__name__, exc)
                continue

            if not track:
                continue

            attempted = tuple(
                dict.fromkeys((*base_metadata.get("fallback_attempts", ()), attempt.kind))
            )
            save_track_metadata(
                track,
                requester_id=base_metadata.get("requester_id"),
                requester=base_metadata.get("requester"),
                guild_id=base_metadata.get("guild_id"),
                original_query=query,
                source_kind=attempt.kind,
                source_label=attempt.label,
                fallback_attempts=attempted,
            )
            return track

        detail = "; ".join(errors[-2:])
        raise ValueError(detail or "LavaSrc/SoundCloud fallback returned no results.")

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
        info = await asyncio.wait_for(
            loop.run_in_executor(None, lambda: extract_ytdlp_info(query)),
            timeout=YTDLP_TIMEOUT,
        )
        LOG.info(
            "[YTDLP] resolved direct stream profile=%s title=%s webpage=%s",
            info.get("profile"),
            info.get("title"),
            info.get("webpage_url"),
        )
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
            source_label=f"yt-dlp direct stream ({info.get('profile')})",
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
        metadata["guild_id"] = metadata.get("guild_id") or player.guild.id
        LOG.info(
            "[FALLBACK] failed_source=%s failed_title=%s attempted=%s reason=%s",
            source_kind,
            track_title(failed_track),
            sorted(attempted),
            readable_error(reason),
        )

        if source_kind in {"soundcloud", "spotify", "applemusic", "deezer", "direct"}:
            if source_kind:
                attempted.add(source_kind)
            metadata["fallback_attempts"] = tuple(attempted)
            await self.send_or_edit_status(
                player,
                "Playback source failed. Trying alternate LavaSrc/SoundCloud mirror...",
            )
            try:
                fallback = await self.search_lavasrc_fallback(query, metadata)
                if fallback:
                    return fallback
            except Exception as exc:
                LOG.warning("[LAVASRC FALLBACK ERROR] %s: %s", type(exc).__name__, exc)

        if "yt-dlp" not in attempted and yt_dlp is not None:
            attempted.add("yt-dlp")
            await self.send_or_edit_status(
                player,
                "Trying yt-dlp direct stream regeneration...",
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
                LOG.warning("[YTDLP FALLBACK ERROR] %s: %s", type(exc).__name__, exc)

        if yt_dlp is None:
            LOG.error("[YTDLP FALLBACK ERROR] yt-dlp is not installed.")

        return None

    async def play_raw(self, player, track):
        LOG.info("[PLAYBACK] starting source=%s title=%s", get_track_metadata(track).get("source_label"), track_title(track))
        await player.play(
            track,
            volume=getattr(player, "shorekeeper_volume", 50),
            populate=False,
        )

    async def skip_player(self, player, *, requested_by=None):
        lock = getattr(player, "shorekeeper_transition_lock", None)
        if lock is None:
            lock = asyncio.Lock()
            player.shorekeeper_transition_lock = lock

        async with lock:
            before_size = queue_size(player)
            requester = getattr(requested_by, "id", requested_by)
            failed_track = None
            failed_error = None
            LOG.info(
                "[SKIP] requested_by=%s current=%s queue_size_before=%s playing=%s paused=%s",
                requester,
                track_title(getattr(player, "current", None)),
                before_size,
                getattr(player, "playing", None),
                getattr(player, "paused", None),
            )

            if queue_empty(player):
                player.shorekeeper_manual_skip_active = True
                try:
                    LOG.info("[SKIP] queue empty; stopping current track only")
                    await player.skip()
                finally:
                    player.shorekeeper_manual_skip_active = False

                await self.update_panel(player.guild.id)
                LOG.info("[SKIP] queue_size_after=%s", queue_size(player))
                return False

            next_track = player.queue.get()
            LOG.info(
                "[SKIP] selected_next=%s queue_size_after_get=%s",
                track_title(next_track),
                queue_size(player),
            )

            player.shorekeeper_manual_skip_active = True
            try:
                await self.send_or_edit_status(
                    player,
                    f"Skipped. Loading next queued track: **{track_title(next_track)}**",
                )
                LOG.info("[SKIP] restarting playback with next queued track")
                await self.play_raw(player, next_track)
                LOG.info("[SKIP] playback restart requested successfully")
                return True
            except Exception as exc:
                LOG.warning(
                    "[SKIP] direct next playback failed for %s: %s: %s",
                    track_title(next_track),
                    type(exc).__name__,
                    exc,
                )
                failed_track = next_track
                failed_error = exc
            finally:
                player.shorekeeper_manual_skip_active = False
                LOG.info("[SKIP] queue_size_after=%s", queue_size(player))

        if failed_track is not None:
            await self.recover_from_failure(player, failed_track, failed_error)
            return False

    async def recover_from_failure(self, player, failed_track, reason):
        current = failed_track

        for attempt in range(1, MAX_TRACK_RECOVERY_ATTEMPTS + 1):
            LOG.warning(
                "[PLAYBACK RECOVERY] attempt=%s failed_track=%s reason=%s",
                attempt,
                track_title(current),
                readable_error(reason),
            )
            fallback = await self.build_next_fallback(player, current, reason)
            if not fallback:
                break

            try:
                await self.play_raw(player, fallback)
                return True
            except Exception as exc:
                LOG.warning(
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
            LOG.debug("[QUEUE] not advancing because player is stopping")
            return False

        lock = getattr(player, "shorekeeper_transition_lock", None)
        if lock is None:
            lock = asyncio.Lock()
            player.shorekeeper_transition_lock = lock

        async with lock:
            LOG.info(
                "[QUEUE] advance requested queue_size=%s playing=%s paused=%s",
                queue_size(player),
                getattr(player, "playing", None),
                getattr(player, "paused", None),
            )

            if queue_empty(player):
                await self.update_panel(player.guild.id)
                LOG.info("[QUEUE] advance aborted; queue empty")
                return False

            next_track = player.queue.get()
            LOG.info(
                "[QUEUE] selected next track=%s queue_size_after_get=%s",
                track_title(next_track),
                queue_size(player),
            )
            await self.send_or_edit_status(
                player,
                f"Loading next queued track: **{track_title(next_track)}**",
            )
            try:
                await self.play_raw(player, next_track)
            except Exception as exc:
                LOG.warning(
                    "[QUEUE] play next failed for %s: %s: %s",
                    track_title(next_track),
                    type(exc).__name__,
                    exc,
                )
                failed_track = next_track
                failed_error = exc
            else:
                return True

        await self.recover_from_failure(player, failed_track, failed_error)
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
            try:
                await session.patch(f"{webhook}/messages/{msg_id}", json=data)
            except Exception as exc:
                LOG.debug("[PANEL] update failed: %s", readable_error(exc))

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
            LOG.warning("[MUSIC SEARCH FAILED] %s: %s", type(exc).__name__, exc)
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
            LOG.info(
                "[QUEUE] queued track=%s queue_size=%s",
                track_title(track),
                queue_size(player),
            )
            await status_message.edit(content=f"Queued: **{track_title(track)}**")
            await self.update_panel(message.guild.id)

    async def command_skip(self, message):
        player = message.guild.voice_client
        if not player or not player.current:
            return await message.channel.send("Nothing is playing.")

        requester_id = get_track_metadata(player.current).get("requester_id")
        if message.author.id != requester_id and not is_mod(message.author):
            return await message.channel.send("Only the requester or mods can skip.")

        await self.skip_player(player, requested_by=message.author)
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

        if not queue_empty(player):
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

        embed.set_footer(text=f"{queue_size(player)} songs queued")
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
            LOG.exception("[WAVELINK COMMAND ERROR] %s: %s", type(exc).__name__, exc)
            await message.channel.send(
                f"Music command failed: {type(exc).__name__}: {exc}"
            )


async def setup(bot):
    if os.getenv("MUSIC_BACKEND", "wavelink").lower() != "wavelink":
        LOG.info("[SKIPPED] cogs.music.wavelink_player: MUSIC_BACKEND is not wavelink")
        return

    if wavelink is None:
        raise RuntimeError(
            "wavelink is not installed. Run `python -m pip install -r requirements.txt`."
        )

    await bot.add_cog(WavelinkMusic(bot))
