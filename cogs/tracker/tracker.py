import discord
from discord.ext import commands, tasks

from cogs.server_config import get_channel_id, is_admin
from cogs.trigger_parser import parse_shorekeeper_trigger
from config.tracker_config import CHECK_INTERVAL, PING_ENABLED, PING_ROLE_ID

from .database import TrackerDB
from .roblox_api import RobloxAPI


class Tracker(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.api = RobloxAPI()
        self.db = TrackerDB()
        self.last_alerts = set()
        self.loop.start()

    def is_allowed(self, member):
        return is_admin(member)

    @tasks.loop(seconds=CHECK_INTERVAL)
    async def loop(self):
        channel = None
        for guild in self.bot.guilds:
            channel_id = get_channel_id(guild.id, "track")
            if channel_id:
                channel = self.bot.get_channel(channel_id)
                if channel:
                    break

        if not channel:
            print("TRACK CHANNEL NOT FOUND")
            return

        for uid, last_status in self.db.all():
            try:
                presence = await self.api.get_presence(uid)
                if not presence:
                    continue

                status = presence["userPresenceType"]
                if status == 2 and last_status != 2:
                    place = presence.get("placeId")
                    job = presence.get("gameId")
                    game = presence.get("lastLocation", "Unknown")
                    key = f"{uid}:{job}"

                    if key in self.last_alerts:
                        continue
                    self.last_alerts.add(key)

                    link = await self.api.get_join_link(place, job) if place and job else None

                    embed = discord.Embed(
                        title="TARGET ACQUIRED",
                        color=discord.Color.green(),
                    )
                    embed.add_field(name="User ID", value=uid)
                    embed.add_field(name="Game", value=game, inline=False)

                    if link:
                        embed.add_field(name="Join", value=link, inline=False)
                    else:
                        fallback = f"https://www.roblox.com/games/{place}"
                        embed.add_field(
                            name="Join",
                            value=f"Server not found\nTry manually:\n{fallback}",
                            inline=False,
                        )

                    content = f"<@&{PING_ROLE_ID}>" if PING_ENABLED else None
                    await channel.send(content=content, embed=embed)

                self.db.update(uid, status)
            except Exception as e:
                print("[TRACK ERROR]", e)

    @loop.before_loop
    async def before(self):
        await self.bot.wait_until_ready()

    @commands.Cog.listener()
    async def on_message(self, message):
        trigger = parse_shorekeeper_trigger(self.bot, message)
        if not trigger:
            return

        if trigger["keyword"] not in {"lookup", "track", "untrack"}:
            return

        if not self.is_allowed(message.author):
            return await message.channel.send("No permission")

        query = trigger["extra"] or " ".join(trigger["args"])
        if not query:
            return await message.channel.send("Provide username or link")

        uid = await self.api.get_user_id(query)
        if not uid:
            return await message.channel.send("User not found")

        if trigger["keyword"] == "lookup":
            presence = await self.api.get_presence(uid)
            status = "Offline"
            game = "None"
            join = "Unavailable"

            if presence["userPresenceType"] == 2:
                status = "In Game"
                game = presence.get("lastLocation", "Unknown")
                place = presence.get("placeId")
                job = presence.get("gameId")

                if place and job:
                    link = await self.api.get_join_link(place, job)
                    if link:
                        join = link
            elif presence["userPresenceType"] == 1:
                status = "Online"

            embed = discord.Embed(title="Lookup", color=discord.Color.blue())
            embed.add_field(name="User ID", value=uid)
            embed.add_field(name="Status", value=status)
            embed.add_field(name="Game", value=game, inline=False)
            embed.add_field(name="Join", value=join, inline=False)
            return await message.channel.send(embed=embed)

        if trigger["keyword"] == "track":
            self.db.add(uid)
            return await message.channel.send(f"Tracking `{query}`")

        self.db.remove(uid)
        return await message.channel.send(f"Stopped tracking `{query}`")


async def setup(bot):
    await bot.add_cog(Tracker(bot))
