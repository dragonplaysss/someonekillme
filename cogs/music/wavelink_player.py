from __future__ import annotations

import os

import discord
from discord.ext import commands

from cogs.server_config import get_channel_id, get_guild_config, is_admin, is_mod
from cogs.trigger_parser import parse_shorekeeper_trigger

try:
    import wavelink
except ImportError:
    wavelink = None


LAVALINK_URI = os.getenv("LAVALINK_URI", "http://127.0.0.1:2333")
LAVALINK_PASSWORD = os.getenv("LAVALINK_PASSWORD", "youshallnotpass")
MUSIC_SEARCH_PROVIDER = os.getenv("MUSIC_SEARCH_PROVIDER", "youtube").lower()
track_metadata = {}


def source_for_provider():
    if wavelink is None:
        return None

    if MUSIC_SEARCH_PROVIDER in {"soundcloud", "sc"}:
        return wavelink.TrackSource.SoundCloud
    if MUSIC_SEARCH_PROVIDER in {"ytmusic", "youtube_music", "youtube-music"}:
        return wavelink.TrackSource.YouTubeMusic
    return wavelink.TrackSource.YouTube


def format_duration(milliseconds):
    if not milliseconds:
        return "Live"

    seconds = int(milliseconds // 1000)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)

    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


def track_title(track):
    return getattr(track, "title", "Unknown")


def track_key(track):
    return getattr(track, "encoded", None) or getattr(track, "identifier", None)


def save_track_metadata(track, **metadata):
    key = track_key(track)
    if key:
        track_metadata[key] = metadata


def get_track_metadata(track):
    return track_metadata.get(track_key(track), {})


def save_many_metadata(tracks, **metadata):
    for track in tracks:
        save_track_metadata(track, **metadata)


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
        await player.disconnect()
        await interaction.response.send_message("Stopped.")


class WavelinkMusic(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.node_ready = False

    async def cog_load(self):
        node = wavelink.Node(uri=LAVALINK_URI, password=LAVALINK_PASSWORD)
        await wavelink.Pool.connect(nodes=[node], client=self.bot)

    @commands.Cog.listener()
    async def on_wavelink_node_ready(self, payload):
        self.node_ready = True
        print(f"[WAVELINK] Node ready: {payload.node.identifier}")

    @commands.Cog.listener()
    async def on_wavelink_track_end(self, payload):
        player = payload.player
        if not player:
            return

        if getattr(player, "shorekeeper_loop", False) and payload.track:
            await player.play(payload.track)
            return

        if player.queue:
            next_track = player.queue.get()
            await player.play(next_track)
            return

        await self.update_panel(player.guild.id)

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

        channel_id = getattr(player, "shorekeeper_text_channel_id", None)
        channel = player.guild.get_channel(channel_id) if channel_id else None
        status_message = await self.get_status_message(player)

        if player.queue:
            next_track = player.queue.get()
            if status_message:
                await status_message.edit(
                    content=f"Playback failed. Trying next result: **{track_title(next_track)}**"
                )
            await player.play(next_track)
            return

        if status_message:
            await status_message.edit(
                content=(
                    "Playback failed on every result. YouTube is resolving tracks but "
                    "refusing the stream on this server. Try `MUSIC_SEARCH_PROVIDER=soundcloud` "
                    "or a direct SoundCloud URL."
                )
            )
        elif channel:
            await channel.send("Playback failed on every result.")

        await player.disconnect()

    def get_author_voice_channel(self, message):
        if not message.author.voice or not message.author.voice.channel:
            return None
        return message.author.voice.channel

    async def ensure_node(self, channel):
        if self.node_ready:
            return True

        try:
            wavelink.Pool.get_node()
            return True
        except Exception:
            await channel.send("Music backend is not connected to Lavalink yet.")
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
            return player

        try:
            return await voice_channel.connect(cls=wavelink.Player, self_deaf=True)
        except Exception as e:
            print(f"[WAVELINK VOICE ERROR] {type(e).__name__}: {e}")
            await message.channel.send(f"Voice connect failed: {type(e).__name__}: {e}")
            return None

    async def search_tracks(self, query):
        if query.startswith(("http://", "https://")):
            results = await wavelink.Playable.search(query)
            if not results:
                raise ValueError("No playable results found for that URL.")
            return list(results)[:5]

        sources = [source_for_provider()]
        if MUSIC_SEARCH_PROVIDER in {"youtube", "yt", "ytmusic", "youtube_music", "youtube-music"}:
            sources.append(wavelink.TrackSource.SoundCloud)
        elif MUSIC_SEARCH_PROVIDER in {"soundcloud", "sc"}:
            sources.append(wavelink.TrackSource.YouTubeMusic)

        tracks = []
        seen = set()

        for source in sources:
            try:
                results = await wavelink.Playable.search(query, source=source)
            except Exception as e:
                print(f"[WAVELINK SEARCH FALLBACK ERROR] {source}: {type(e).__name__}: {e}")
                continue

            for track in list(results)[:5]:
                key = track_key(track)
                if key in seen:
                    continue
                seen.add(key)
                tracks.append(track)

            if tracks and source == wavelink.TrackSource.SoundCloud:
                break

        if tracks:
            return tracks[:8]

        raise ValueError(f"No playable results found on {MUSIC_SEARCH_PROVIDER}.")

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

    async def clear_status_message(self, player):
        status_message = await self.get_status_message(player)
        if status_message:
            try:
                await status_message.delete()
            except Exception:
                pass

    async def search_track(self, query):
        if query.startswith(("http://", "https://")):
            results = await wavelink.Playable.search(query)
        else:
            results = await wavelink.Playable.search(query, source=source_for_provider())

        if not results:
            raise ValueError(f"No playable results found on {MUSIC_SEARCH_PROVIDER}.")

        return list(results)[:5]

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

    async def send_now_playing(self, message, player):
        track = player.current
        if not track:
            return

        requester = get_track_metadata(track).get("requester", message.author.mention)
        embed = discord.Embed(
            title="Now Playing",
            description=f"**{track_title(track)}**",
            color=0x5865F2,
        )
        embed.add_field(name="Duration", value=format_duration(getattr(track, "length", 0)))
        embed.add_field(name="Requested By", value=requester)

        artwork = getattr(track, "artwork", None)
        if artwork:
            embed.set_thumbnail(url=artwork)

        await message.channel.send(embed=embed, view=WavelinkMusicControls(self.bot))

    async def announce_now_playing(self, player, track):
        channel_id = getattr(player, "shorekeeper_text_channel_id", None)
        channel = player.guild.get_channel(channel_id) if channel_id else None
        if not channel:
            return

        await self.clear_status_message(player)

        requester = get_track_metadata(track).get("requester", "Unknown")
        embed = discord.Embed(
            title="Now Playing",
            description=f"**{track_title(track)}**",
            color=0x5865F2,
        )
        embed.add_field(name="Duration", value=format_duration(getattr(track, "length", 0)))
        embed.add_field(name="Requested By", value=requester)

        artwork = getattr(track, "artwork", None)
        if artwork:
            embed.set_thumbnail(url=artwork)

        await channel.send(embed=embed, view=WavelinkMusicControls(self.bot))

    async def command_play(self, message, query):
        music_channel_id = get_channel_id(message.guild.id, "music")
        if music_channel_id and message.channel.id != music_channel_id:
            return

        if not await self.ensure_node(message.channel):
            return

        status_message = await message.channel.send(f"Searching: **{query}**")

        try:
            tracks = await self.search_tracks(query)
        except Exception as e:
            print(f"[WAVELINK SEARCH ERROR] {type(e).__name__}: {e}")
            return await status_message.edit(content=f"Search failed: {type(e).__name__}: {e}")

        track = tracks[0]
        fallback_tracks = tracks[1:]

        save_many_metadata(
            tracks,
            requester_id=message.author.id,
            requester=message.author.mention,
            text_channel_id=message.channel.id,
        )

        player = await self.ensure_connected(message)
        if not player:
            return

        player.shorekeeper_text_channel_id = message.channel.id
        player.shorekeeper_status_message_id = status_message.id
        player.shorekeeper_loop = getattr(player, "shorekeeper_loop", False)

        if not player.playing:
            await status_message.edit(content=f"Loading: **{track_title(track)}**")
            for fallback in fallback_tracks:
                player.queue.put(fallback)
            await player.play(track, volume=50)
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
                value="\n".join(f"`{i + 1}` - {track_title(t)}" for i, t in enumerate(tracks)),
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
        except Exception as e:
            print(f"[WAVELINK COMMAND ERROR] {type(e).__name__}: {e}")
            await message.channel.send(f"Music command failed: {type(e).__name__}: {e}")


async def setup(bot):
    if os.getenv("MUSIC_BACKEND", "ytdlp").lower() != "wavelink":
        print("[SKIPPED] cogs.music.wavelink_player: MUSIC_BACKEND is not wavelink")
        return

    if wavelink is None:
        raise RuntimeError("wavelink is not installed. Run `python -m pip install -r requirements.txt`.")

    await bot.add_cog(WavelinkMusic(bot))
