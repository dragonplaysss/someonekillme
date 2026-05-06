import aiohttp
import discord
from discord.ext import commands

from cogs.server_config import is_panel_owner, update_guild_config
from cogs.trigger_parser import parse_shorekeeper_trigger


class MusicSetup(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def setup_music_panel(self, channel):
        webhook = await channel.create_webhook(name="Music Panel")

        async with aiohttp.ClientSession() as session:
            wh = discord.Webhook.from_url(webhook.url, session=session)
            msg = await wh.send(
                embed=discord.Embed(
                    title="Music Player",
                    description="Idle",
                    color=0x5865F2,
                ),
                wait=True,
            )

        def updater(config):
            config.setdefault("channels", {})["music"] = channel.id
            config.setdefault("music", {})["webhook_url"] = webhook.url
            config.setdefault("music", {})["message_id"] = str(msg.id)

        update_guild_config(channel.guild.id, updater)

    @commands.Cog.listener()
    async def on_message(self, message):
        trigger = parse_shorekeeper_trigger(self.bot, message)
        if not trigger or trigger["keyword"] != "setupmusic":
            return

        if not is_panel_owner(message.author.id):
            return await message.channel.send("You are not allowed to use this command.")

        try:
            await self.setup_music_panel(message.channel)
            await message.channel.send("Music system setup complete.")
        except Exception as e:
            await message.channel.send(f"Music setup failed: {e}")
