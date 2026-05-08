import datetime
import re

import discord
from discord.ext import commands

from cogs.server_config import get_channel_id, is_admin, is_mod
from cogs.trigger_parser import parse_shorekeeper_trigger
from cogs.mongo_client import get_mongo_database


class ModerationCore(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db = get_mongo_database()
        self.warns = self.db["warns"]
        self.mod_actions = self.db["mod_actions"]

    def is_admin(self, member):
        return is_admin(member)

    def is_mod(self, member):
        return is_mod(member)

    def parse_duration(self, content):
        match = re.search(r"(\d+)([smhd])", content)
        if not match:
            return datetime.timedelta(minutes=10)

        amount, unit = int(match.group(1)), match.group(2)
        units = {"s": "seconds", "m": "minutes", "h": "hours", "d": "days"}
        return datetime.timedelta(**{units[unit]: amount})

    async def cog_load(self):
        await self.warns.create_index([("guild_id", 1), ("user_id", 1)])
        await self.mod_actions.create_index([("guild_id", 1), ("timestamp", -1)])

    async def send_mod_dm(self, target, guild, action, reason):
        if not isinstance(target, (discord.Member, discord.User)):
            return
        embed = discord.Embed(
            title="Moderation Notice",
            description="A moderation action was taken in a server you are in.",
            color=discord.Color.orange(),
        )
        embed.add_field(name="Server", value=guild.name, inline=False)
        embed.add_field(name="Action", value=action, inline=True)
        embed.add_field(name="Reason", value=reason, inline=False)
        try:
            await target.send(embed=embed)
        except Exception:
            pass

    async def send_mod_log(self, guild, action, moderator, target_label, reason):
        mod_logs_id = get_channel_id(guild.id, "mod_logs") or get_channel_id(guild.id, "logging")
        channel = guild.get_channel(mod_logs_id) if mod_logs_id else None
        if not channel:
            return
        embed = discord.Embed(title=f"Moderation: {action}", color=0xE74C3C)
        embed.add_field(name="Target", value=target_label, inline=False)
        embed.add_field(name="Moderator", value=moderator.mention, inline=True)
        embed.add_field(name="Reason", value=reason, inline=False)
        await channel.send(embed=embed)

    async def persist_action(self, guild_id, moderator_id, target_id, action, reason):
        await self.mod_actions.insert_one(
            {
                "guild_id": guild_id,
                "moderator_id": moderator_id,
                "target_id": target_id,
                "action": action,
                "reason": reason,
                "timestamp": discord.utils.utcnow(),
            }
        )

    @commands.Cog.listener()
    async def on_message(self, message):
        try:
            await self.handle_message(message)
        except Exception as e:
            print(f"[ModerationCore Error] {type(e).__name__}: {e}")
            try:
                await message.channel.send(f"Moderation handler error: {type(e).__name__}: {e}")
            except Exception:
                pass

    async def handle_message(self, message):
        trigger = parse_shorekeeper_trigger(self.bot, message)
        if not trigger:
            return

        keyword = trigger["keyword"]
        target = trigger["target"]
        target_id = trigger["target_id"]
        reason = trigger["extra"] or "No reason."

        is_admin = self.is_admin(message.author)
        is_mod = self.is_mod(message.author)

        if keyword == "modtest":
            return await message.channel.send(
                f"Moderation core online. admin={is_admin} mod={is_mod}"
            )

        if keyword == "ban":
            if not is_admin:
                return await message.channel.send("No permission.")
            if not target_id:
                return await message.channel.send("Use `@Shorekeeper ban @user ; reason`.")

            try:
                ban_target = target or discord.Object(id=target_id)
                await message.guild.ban(ban_target, reason=reason)

                target_label = f"{target.mention} ({target.id})" if target else f"<@{target_id}> ({target_id})"
                await self.send_mod_dm(target, message.guild, "Ban", reason)
                await self.send_mod_log(message.guild, "Ban", message.author, target_label, reason)
                await self.persist_action(message.guild.id, message.author.id, target_id, "ban", reason)
                await message.channel.send(f"Banned {target_label}.")
            except Exception as e:
                await message.channel.send(f"Ban failed: {e}")

        elif keyword == "kick":
            if not is_mod:
                return await message.channel.send("No permission.")
            if not target:
                return await message.channel.send("Mention a user to kick.")

            try:
                await target.kick(reason=reason)
                await self.send_mod_dm(target, message.guild, "Kick", reason)
                await self.send_mod_log(
                    message.guild, "Kick", message.author, f"{target.mention} ({target.id})", reason
                )
                await self.persist_action(message.guild.id, message.author.id, target.id, "kick", reason)
                await message.channel.send(f"Kicked {target.mention}.")
            except Exception as e:
                await message.channel.send(f"Kick failed: {e}")

        elif keyword == "unban":
            if not is_admin:
                return await message.channel.send("No permission.")
            if not target_id:
                return await message.channel.send("Use `@Shorekeeper unban @user_or_id ; reason`.")

            try:
                await message.guild.unban(discord.Object(id=target_id), reason=reason)
                await self.send_mod_log(
                    message.guild, "Unban", message.author, f"<@{target_id}> ({target_id})", reason
                )
                await self.persist_action(message.guild.id, message.author.id, target_id, "unban", reason)
                await message.channel.send(f"Unbanned `{target_id}`.")
            except discord.NotFound:
                await message.channel.send("That user is not banned.")
            except Exception as e:
                await message.channel.send(f"Unban failed: {e}")

        elif keyword == "mute":
            if not is_mod:
                return await message.channel.send("No permission.")
            if not target:
                return await message.channel.send("Use `@Shorekeeper mute @user ; reason`.")

            try:
                duration = self.parse_duration(trigger["main"])
                await target.timeout(discord.utils.utcnow() + duration, reason=reason)
                await self.send_mod_dm(target, message.guild, "Mute", reason)
                await self.send_mod_log(
                    message.guild, "Mute", message.author, f"{target.mention} ({target.id})", reason
                )
                await self.persist_action(message.guild.id, message.author.id, target.id, "mute", reason)
                await message.channel.send(f"Muted {target.mention} for {duration}.")
            except Exception as e:
                await message.channel.send(f"Mute failed: {e}")

        elif keyword in {"unmute", "untimeout"}:
            if not is_mod:
                return await message.channel.send("No permission.")
            if not target:
                return await message.channel.send("Use `@Shorekeeper unmute @user ; reason`.")

            try:
                await target.timeout(None, reason=reason)
                await self.send_mod_log(
                    message.guild, "Unmute", message.author, f"{target.mention} ({target.id})", reason
                )
                await self.persist_action(message.guild.id, message.author.id, target.id, "unmute", reason)
                await message.channel.send(f"Unmuted {target.mention}.")
            except Exception as e:
                await message.channel.send(f"Unmute failed: {e}")

        elif keyword == "warn":
            if not is_mod:
                return await message.channel.send("No permission.")
            if not target:
                return await message.channel.send("Use `@Shorekeeper warn @user ; reason`.")

            await self.warns.insert_one(
                {
                    "guild_id": message.guild.id,
                    "user_id": target.id,
                    "moderator_id": message.author.id,
                    "reason": reason,
                    "timestamp": discord.utils.utcnow(),
                }
            )
            count = await self.warns.count_documents(
                {"guild_id": message.guild.id, "user_id": target.id}
            )
            await self.send_mod_dm(target, message.guild, "Warn", reason)
            await self.send_mod_log(
                message.guild,
                "Warn",
                message.author,
                f"{target.mention} ({target.id})",
                f"{reason}\nTotal warns: {count}",
            )
            await self.persist_action(message.guild.id, message.author.id, target.id, "warn", reason)
            await message.channel.send(f"Warned {target.mention}. Total warns: `{count}`")

        elif keyword in {"purge", "clear"}:
            if not is_mod:
                return await message.channel.send("No permission.")

            try:
                amount = next((int(arg) for arg in trigger["args"] if arg.isdigit()), None)
                if amount is None:
                    return await message.channel.send("Provide a number.")
                if amount > 50:
                    return await message.channel.send("Max purge is 50.")

                await message.channel.purge(limit=amount)
                await message.channel.send(f"Deleted {amount} messages", delete_after=3)
            except Exception as e:
                await message.channel.send(f"Purge failed: {e}")


async def setup(bot):
    await bot.add_cog(ModerationCore(bot))
