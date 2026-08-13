import discord
from discord.ext import commands

from cogs.mongo_client import get_mongo_database
from cogs.server_config import get_channel_id, immunity_reason, is_admin
from cogs.trigger_parser import parse_shorekeeper_trigger


class NickLockCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db = get_mongo_database()
        self.nick_locks = self.db["nick_locks"]

    async def cog_load(self):
        await self.nick_locks.create_index([("guild_id", 1), ("user_id", 1)], unique=True)

    async def send_log(self, guild, action, moderator, target, details):
        mod_logs_id = get_channel_id(guild.id, "mod_logs") or get_channel_id(guild.id, "logging")
        channel = guild.get_channel(mod_logs_id) if mod_logs_id else None
        if not channel:
            return
        embed = discord.Embed(title=f"NickLock: {action}", color=0x3498DB)
        embed.add_field(name="Target", value=f"{target.mention} ({target.id})", inline=False)
        embed.add_field(name="Moderator", value=moderator.mention, inline=True)
        embed.add_field(name="Details", value=details, inline=False)
        await channel.send(embed=embed)

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        if before.nick == after.nick:
            return

        lock = await self.nick_locks.find_one({"guild_id": after.guild.id, "user_id": after.id})
        if not lock:
            return
        if immunity_reason(after, "nicklock"):
            await self.nick_locks.delete_one({"guild_id": after.guild.id, "user_id": after.id})
            return

        locked_nick = lock.get("nick")
        if after.nick == locked_nick:
            return
        try:
            await after.edit(nick=locked_nick, reason="Nickname is locked by Shorekeeper.")
        except Exception as exc:
            print(f"[NICKLOCK] Failed enforcing nick lock: {type(exc).__name__}: {exc}")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        trigger = parse_shorekeeper_trigger(self.bot, message)
        if not trigger:
            return
        if message.author.bot or not message.guild:
            return

        keyword = trigger["keyword"]
        target = trigger["target"]
        extra = trigger["extra"]

        if keyword == "locknick":
            if not is_admin(message.author):
                return await message.channel.send("No permission.")
            if not target:
                return await message.channel.send("Use `@Shorekeeper locknick @user ; nickname`.")
            protected = immunity_reason(target, "nicklock")
            if protected:
                await self.send_log(message.guild, "Blocked Lock", message.author, target, protected)
                return await message.channel.send(protected)
            new_nick = (extra or "").strip()
            if not new_nick:
                return await message.channel.send("Provide nickname after `;`.")
            if len(new_nick) > 32:
                return await message.channel.send("Nickname must be <= 32 characters.")

            await self.nick_locks.update_one(
                {"guild_id": message.guild.id, "user_id": target.id},
                {
                    "$set": {
                        "nick": new_nick,
                        "locked_by": message.author.id,
                        "updated_at": discord.utils.utcnow(),
                    }
                },
                upsert=True,
            )
            try:
                await target.edit(nick=new_nick, reason=f"Nickname locked by {message.author}")
            except Exception as exc:
                return await message.channel.send(f"Nick lock saved, but applying failed: {exc}")

            await self.send_log(message.guild, "Lock", message.author, target, f"Locked as `{new_nick}`")
            return await message.channel.send(f"Nickname locked for {target.mention} as `{new_nick}`.")

        if keyword == "unlocknick":
            if not is_admin(message.author):
                return await message.channel.send("No permission.")
            if not target:
                return await message.channel.send("Use `@Shorekeeper unlocknick @user ; reason`.")

            result = await self.nick_locks.delete_one({"guild_id": message.guild.id, "user_id": target.id})
            if result.deleted_count == 0:
                return await message.channel.send("That user has no nick lock.")

            try:
                await target.edit(nick=None, reason=f"Nickname unlocked by {message.author}")
            except Exception:
                pass

            reason = extra or "No reason."
            await self.send_log(message.guild, "Unlock", message.author, target, reason)
            return await message.channel.send(f"Nickname unlocked for {target.mention}.")

        if keyword == "nicklocks":
            if not is_admin(message.author):
                return await message.channel.send("No permission.")
            docs = (
                await self.nick_locks.find({"guild_id": message.guild.id}).sort("updated_at", -1).limit(20).to_list(20)
            )
            if not docs:
                return await message.channel.send("No nick locks are active.")
            lines = []
            for doc in docs:
                user = message.guild.get_member(doc["user_id"])
                label = user.mention if user else f"<@{doc['user_id']}>"
                lines.append(f"- {label} -> `{doc.get('nick', 'Unknown')}`")
            embed = discord.Embed(title="Active Nick Locks", description="\n".join(lines), color=0x3498DB)
            await message.channel.send(embed=embed)


async def setup(bot):
    await bot.add_cog(NickLockCog(bot))
