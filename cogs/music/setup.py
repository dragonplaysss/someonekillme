import aiohttp
import discord
import logging
from discord.ext import commands

from cogs.server_config import is_panel_owner, update_guild_config
from cogs.trigger_parser import parse_shorekeeper_trigger


LOG = logging.getLogger("shorekeeper.music.setup")
MUSIC_WEBHOOK_AVATAR_URL = (
    "https://cdn.discordapp.com/attachments/1489351992118874177/"
    "1501576039120240744/35zhtfq.png"
)


class MusicSetup(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def fetch_webhook_avatar(self):
        timeout = aiohttp.ClientTimeout(total=10)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(MUSIC_WEBHOOK_AVATAR_URL) as resp:
                    content_type = resp.headers.get("Content-Type", "")
                    if resp.status != 200 or not content_type.startswith("image/"):
                        LOG.warning(
                            "[SETUPMUSIC] avatar fetch skipped status=%s content_type=%s",
                            resp.status,
                            content_type,
                        )
                        return None
                    return await resp.read()
        except Exception as exc:
            LOG.warning("[SETUPMUSIC] avatar fetch failed: %s: %s", type(exc).__name__, exc)
            return None

    async def setup_music_panel(self, channel):
        bot_member = channel.guild.me or channel.guild.get_member(self.bot.user.id)
        if bot_member is None:
            raise RuntimeError("I could not resolve my server member permissions yet.")

        permissions = channel.permissions_for(bot_member)
        if not permissions.manage_webhooks:
            raise RuntimeError("I need Manage Webhooks permission in this channel.")
        if not permissions.send_messages:
            raise RuntimeError("I need Send Messages permission in this channel.")

        avatar_bytes = await self.fetch_webhook_avatar()
        webhook_kwargs = {"name": "Shorekeeper Music"}
        if avatar_bytes:
            webhook_kwargs["avatar"] = avatar_bytes

        LOG.info("[SETUPMUSIC] creating music webhook guild=%s channel=%s", channel.guild.id, channel.id)
        webhook = await channel.create_webhook(**webhook_kwargs)

        async with aiohttp.ClientSession() as session:
            wh = discord.Webhook.from_url(webhook.url, session=session)
            msg = await wh.send(
                embed=discord.Embed(
                    title="Music Queue",
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
        if message.author.bot or not message.guild:
            return

        trigger = parse_shorekeeper_trigger(self.bot, message)
        if not trigger or trigger["keyword"] != "setupmusic":
            return

        if not is_panel_owner(message.author.id):
            return await message.channel.send("You are not allowed to use this command.")

        try:
            await self.setup_music_panel(message.channel)
            await message.channel.send("Music system setup complete.")
        except Exception as e:
            LOG.exception("[SETUPMUSIC] failed: %s: %s", type(e).__name__, e)
            await message.channel.send(f"Music setup failed: {e}")


async def setup(bot):
    await bot.add_cog(MusicSetup(bot))
