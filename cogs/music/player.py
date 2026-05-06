import asyncio
from dataclasses import dataclass, field
from email.mime import message

import aiohttp
import discord
import yt_dlp
from discord.ext import commands

from cogs.server_config import get_channel_id, get_guild_config, is_mod
from cogs.trigger_parser import parse_shorekeeper_trigger

ytdl = yt_dlp.YoutubeDL(
    {
        "format": "bestaudio/best",
        "noplaylist": True,
        "default_search": "ytsearch",
        "quiet": True,
        "extractor_args": {
            "youtube": {
                "player_client": ["android", "web"],
            }
        },
    }
)

FFMPEG_BEFORE_OPTIONS = "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5"


@dataclass
class Song:
    title: str
    url: str
    duration: str
    requester_id: int
    requester: str
    thumbnail: str | None = None


@dataclass
class PlayerState:
    guild_id: int
    voice_channel_id: int
    text_channel_id: int
    queue: list[Song] = field(default_factory=list)
    now: Song | None = None
    loop: bool = False
    volume: float = 0.5
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


players: dict[tuple[int, int], PlayerState] = {}


def player_key(guild_id, voice_channel_id):
    return guild_id, voice_channel_id


def format_queue(player):
    if not player.queue:
        return "Queue is empty."
    return "\n".join(
        f"{index + 1}. {song.title} ({song.duration}) - {song.requester}"
        for index, song in enumerate(player.queue[:10])
    )


class MusicControls(discord.ui.View):
    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot

    async def can_control(self, interaction):
        player = get_player_for_interaction(interaction)
        if not player or not player.now:
            await interaction.response.send_message(
                "Nothing is playing.", ephemeral=True
            )
            return None

        cfg = get_guild_config(interaction.guild.id)
        skip_role_id = cfg.get("skip_role")
        has_skip_role = skip_role_id and any(
            role.id == skip_role_id for role in interaction.user.roles
        )

        if (
            interaction.user.id == player.now.requester_id
            or has_skip_role
            or is_mod(interaction.user)
        ):
            return player

        await interaction.response.send_message("No permission.", ephemeral=True)
        return None

    @discord.ui.button(label="Skip", style=discord.ButtonStyle.danger)
    async def skip(self, interaction: discord.Interaction, button: discord.ui.Button):
        player = await self.can_control(interaction)
        if not player:
            return
        vc = interaction.guild.voice_client
        if vc:
            vc.stop()
        await interaction.response.send_message("Skipped.")

    @discord.ui.button(label="Pause", style=discord.ButtonStyle.secondary)
    async def pause(self, interaction: discord.Interaction, button: discord.ui.Button):
        player = await self.can_control(interaction)
        if not player:
            return
        vc = interaction.guild.voice_client
        if vc and vc.is_playing():
            vc.pause()
        await interaction.response.send_message("Paused.")

    @discord.ui.button(label="Resume", style=discord.ButtonStyle.success)
    async def resume(self, interaction: discord.Interaction, button: discord.ui.Button):
        player = await self.can_control(interaction)
        if not player:
            return
        vc = interaction.guild.voice_client
        if vc and vc.is_paused():
            vc.resume()
        await interaction.response.send_message("Resumed.")

    @discord.ui.button(label="Loop", style=discord.ButtonStyle.primary)
    async def loop(self, interaction: discord.Interaction, button: discord.ui.Button):
        player = await self.can_control(interaction)
        if not player:
            return
        player.loop = not player.loop
        await interaction.response.send_message(
            f"Loop is now {'ON' if player.loop else 'OFF'}."
        )

    @discord.ui.button(label="Stop", style=discord.ButtonStyle.danger)
    async def stop(self, interaction: discord.Interaction, button: discord.ui.Button):
        player = await self.can_control(interaction)
        if not player:
            return
        player.queue.clear()
        player.now = None
        vc = interaction.guild.voice_client
        if vc:
            vc.stop()
            await vc.disconnect()
        await interaction.response.send_message("Stopped.")


def get_player_for_interaction(interaction):
    if not interaction.guild or not interaction.guild.voice_client:
        return None
    channel = interaction.guild.voice_client.channel
    return players.get(player_key(interaction.guild.id, channel.id))


class Music(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def get_author_voice_channel(self, message):
        if not message.author.voice or not message.author.voice.channel:
            return None
        return message.author.voice.channel

    def get_player(self, message):
        voice_channel = self.get_author_voice_channel(message)
        if not voice_channel:
            return None

        key = player_key(message.guild.id, voice_channel.id)
        if key not in players:
            players[key] = PlayerState(
                guild_id=message.guild.id,
                voice_channel_id=voice_channel.id,
                text_channel_id=message.channel.id,
            )
        else:
            players[key].text_channel_id = message.channel.id
        return players[key]

    async def update_panel(self, guild_id):
        cfg = get_guild_config(guild_id).get("music", {})
        webhook = cfg.get("webhook_url")
        msg_id = cfg.get("message_id")
        if not webhook or not msg_id:
            return

        active = [p for p in players.values() if p.guild_id == guild_id and p.now]
        if not active:
            description = "Idle"
        else:
            lines = []
            for player in active[:5]:
                channel = self.bot.get_channel(player.voice_channel_id)
                name = channel.name if channel else str(player.voice_channel_id)
                lines.append(f"**{name}:** {player.now.title} ({player.now.duration})")
            description = "\n".join(lines)

        data = {
            "embeds": [
                {
                    "title": "Music Player",
                    "description": description,
                    "color": 0x5865F2,
                }
            ]
        }

        async with aiohttp.ClientSession() as session:
            await session.patch(f"{webhook}/messages/{msg_id}", json=data)

    async def extract_song(self, query, requester):
        data = await self.bot.loop.run_in_executor(
            None, lambda: ytdl.extract_info(query, download=False)
        )
        entry = data["entries"][0] if "entries" in data else data
        duration = entry.get("duration", 0) or 0
        return Song(
            title=entry.get("title", "Unknown"),
            url=entry.get("url") or entry["formats"][0]["url"],
            duration=f"{duration // 60}:{str(duration % 60).zfill(2)}",
            requester_id=requester.id,
            requester=requester.mention,
            thumbnail=entry.get("thumbnail"),
        )

    async def ensure_connected(self, message):
        voice_channel = self.get_author_voice_channel(message)
        if not voice_channel:
            await message.channel.send("Join a voice channel first.")
            return None

        vc = message.guild.voice_client
        if vc and vc.channel.id != voice_channel.id:
            await vc.move_to(voice_channel)
        elif not vc:
            vc = await voice_channel.connect()
        return vc

    async def play_next(self, guild, player):
        async with player.lock:
            vc = guild.voice_client
            if not vc:
                return

            if player.loop and player.now:
                song = player.now
            elif player.queue:
                song = player.queue.pop(0)
            else:
                player.now = None
                await self.update_panel(guild.id)
                if vc.is_connected():
                    await vc.disconnect()
                return

            player.now = song
            source = discord.PCMVolumeTransformer(
                discord.FFmpegPCMAudio(
                    song.url,
                    before_options=FFMPEG_BEFORE_OPTIONS,
                    options="-vn",
                ),
                volume=player.volume,
            )
            vc.play(
                source,
                after=lambda error: self.bot.loop.create_task(
                    self.play_next(guild, player)
                ),
            )

        await self.update_panel(guild.id)

        text_channel = guild.get_channel(player.text_channel_id)

        if text_channel:
            embed = discord.Embed(
                title="Now Playing",
                description=f"**{song.title}**",
                color=0x5865F2,
            )

            embed.add_field(name="Duration", value=song.duration)
            embed.add_field(name="Requested By", value=song.requester)

            embed.add_field(
                name="Progress",
                value="▰▰▰▰▱▱▱▱▱▱",
                inline=False,
            )

            if song.thumbnail:
                embed.set_thumbnail(url=song.thumbnail)

            await text_channel.send(
                embed=embed,
                view=MusicControls(self.bot),
            )

    async def command_play(self, message, query):
        music_channel_id = get_channel_id(message.guild.id, "music")
        if music_channel_id and message.channel.id != music_channel_id:
            return

        vc = await self.ensure_connected(message)
        if not vc:
            return

        player = self.get_player(message)
        async with message.channel.typing():
            song = await self.extract_song(query, message.author)
        player.queue.append(song)

        if not vc.is_playing() and not vc.is_paused():
            await self.play_next(message.guild, player)
        else:
            await message.channel.send(f"Queued: **{song.title}**")
            await self.update_panel(message.guild.id)

    async def command_skip(self, message):
        vc = message.guild.voice_client

        if not vc:
            return await message.channel.send("Nothing is playing.")

        player = self.get_player(message)

        if (
            player
            and player.now
            and message.author.id != player.now.requester_id
            and not is_mod(message.author)
        ):
            return await message.channel.send("Only the requester or mods can skip.")

        vc.stop()

        await message.channel.send("Skipped.")

    async def command_pause(self, message):
        vc = message.guild.voice_client
        if vc and vc.is_playing():
            vc.pause()
            return await message.channel.send("Paused.")
        await message.channel.send("Nothing is playing.")

    async def command_resume(self, message):
        vc = message.guild.voice_client
        if vc and vc.is_paused():
            vc.resume()
            return await message.channel.send("Resumed.")
        await message.channel.send("Nothing is paused.")

    async def command_stop(self, message):
        player = self.get_player(message)
        if player:
            player.queue.clear()
            player.now = None

        vc = message.guild.voice_client
        if vc:
            vc.stop()
            await vc.disconnect()
        await self.update_panel(message.guild.id)
        await message.channel.send("Stopped.")


    async def command_queue(self, message):
        player = self.get_player(message)

        if not player:
            return await message.channel.send("Join a voice channel first.")

        embed = discord.Embed(
            title="Music Queue",
            color=0x5865F2,
        )

        if player.now:
            embed.add_field(
                name="Now Playing",
                value=f"**{player.now.title}** ({player.now.duration})",
                inline=False,
            )

        if player.queue:
            embed.add_field(
                name="Up Next",
                value="\n".join(
                    f"`{index + 1}` • {song.title} ({song.duration})"
                    for index, song in enumerate(player.queue[:10])
                ),
                inline=False,
            )
        else:
            embed.add_field(
                name="Up Next",
                value="Queue is empty.",
                inline=False,
            )

        embed.set_footer(text=f"{len(player.queue)} songs queued")

        await message.channel.send(embed=embed)

    async def command_nowplaying(self, message):
        player = self.get_player(message)
        if not player or not player.now:
            return await message.channel.send("Nothing is playing.")
        await message.channel.send(
            f"Now playing: **{player.now.title}** ({player.now.duration})"
        )

    async def command_loop(self, message):
        player = self.get_player(message)
        if not player:
            return await message.channel.send("Join a voice channel first.")
        player.loop = not player.loop
        await message.channel.send(f"Loop is now {'ON' if player.loop else 'OFF'}.")

    async def command_volume(self, message, value):
        player = self.get_player(message)
        if not player:
            return await message.channel.send("Join a voice channel first.")
        try:
            amount = max(0, min(100, int(value)))
        except ValueError:
            return await message.channel.send("Volume must be 0-100.")
        player.volume = amount / 100
        vc = message.guild.voice_client
        if vc and isinstance(vc.source, discord.PCMVolumeTransformer):
            vc.source.volume = player.volume
        await message.channel.send(f"Volume set to {amount}%.")

    @commands.Cog.listener()
    async def on_message(self, message):
        trigger = parse_shorekeeper_trigger(self.bot, message)
        if not trigger:
            return

        keyword = trigger["keyword"]
        query = trigger["extra"] or " ".join(trigger["args"])

        if keyword == "play":
            if not query:
                return await message.channel.send(
                    "Use `@shorekeeper play ; song name`."
                )
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
