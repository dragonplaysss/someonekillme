import datetime
import json
import os
import re

import discord
from discord.ext import commands

from cogs.server_config import get_channel_id, is_admin, is_mod
from cogs.trigger_parser import parse_shorekeeper_trigger


NICK_PATH = "cogs/moderation/data2/nick_lock.json"


def load_json(path, default):
    if not os.path.exists(path):
        save_json(path, default)
        return json.loads(json.dumps(default))
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError("JSON root must be an object.")
        return data
    except (json.JSONDecodeError, ValueError):
        print(f"[Config Error] {path} is empty or invalid; using defaults.")
        save_json(path, default)
        return json.loads(json.dumps(default))


def save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)


def load_nick_db():
    return load_json(NICK_PATH, {"locked": {}})


def save_nick_db(data):
    save_json(NICK_PATH, data)


class ModerationCore(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def is_admin(self, member):
        return is_admin(member)

    def is_mod(self, member):
        return is_mod(member)

    @commands.Cog.listener()
    async def on_member_update(self, before, after):
        if before.nick == after.nick:
            return

        db = load_nick_db()
        locked = db.get("locked", {})

        if str(after.id) in locked:
            locked_nick = locked[str(after.id)]
            if after.nick != locked_nick:
                try:
                    await after.edit(nick=locked_nick)
                except Exception as e:
                    print(f"[Nick Error] {e}")

    def parse_duration(self, content):
        match = re.search(r"(\d+)([smhd])", content)
        if not match:
            return datetime.timedelta(minutes=10)

        amount, unit = int(match.group(1)), match.group(2)
        units = {"s": "seconds", "m": "minutes", "h": "hours", "d": "days"}
        return datetime.timedelta(**{units[unit]: amount})

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

        blacklist_chan = message.guild.get_channel(get_channel_id(message.guild.id, "blacklist"))
        logging_chan = message.guild.get_channel(get_channel_id(message.guild.id, "logging"))

        is_admin = self.is_admin(message.author)
        is_mod = self.is_mod(message.author)

        if keyword == "modtest":
            return await message.channel.send(
                f"Moderation core online. admin={is_admin} mod={is_mod}"
            )

        if keyword in {"blacklist", "ban"}:
            if not is_admin:
                return await message.channel.send("No permission.")
            if not target_id:
                return await message.channel.send("Provide a user mention or ID to blacklist.")

            try:
                ban_target = target or discord.Object(id=target_id)
                await message.guild.ban(ban_target, reason=reason)

                target_label = (
                    f"{target.mention} ({target.id})"
                    if target
                    else f"<@{target_id}> ({target_id})"
                )

                embed = discord.Embed(title="Blacklisted", color=0xFF0000)
                embed.add_field(name="User", value=target_label)
                embed.add_field(name="By", value=message.author.mention)
                embed.add_field(name="Reason", value=reason, inline=False)

                for channel in (blacklist_chan, logging_chan):
                    if channel:
                        await channel.send(embed=embed)
                await message.channel.send(f"Blacklisted `{target_id}`.")
            except Exception as e:
                await message.channel.send(f"Blacklist failed: {e}")

        elif keyword == "kick":
            if not is_mod:
                return await message.channel.send("No permission.")
            if not target:
                return await message.channel.send("Mention a user to kick.")

            try:
                await target.kick(reason=reason)

                embed = discord.Embed(title="Kicked", color=0xFFAA00)
                embed.add_field(name="User", value=f"{target} ({target.id})")
                embed.add_field(name="By", value=message.author.mention)
                embed.add_field(name="Reason", value=reason, inline=False)

                await message.channel.send(embed=embed)
                if logging_chan:
                    await logging_chan.send(embed=embed)
            except Exception as e:
                await message.channel.send(f"Kick failed: {e}")

        elif keyword in {"unblacklist", "unban"}:
            if not is_admin:
                return await message.channel.send("No permission.")
            if not target_id:
                return await message.channel.send("Provide a user ID to unblacklist.")

            try:
                await message.guild.unban(discord.Object(id=target_id), reason=reason)

                embed = discord.Embed(
                    title="Unblacklisted",
                    description=f"User `{target_id}` restored.",
                    color=0x00FF00,
                )
                embed.add_field(name="By", value=message.author.mention)

                await message.channel.send(embed=embed)
                if logging_chan:
                    await logging_chan.send(embed=embed)
            except discord.NotFound:
                await message.channel.send("That user is not banned.")
            except Exception as e:
                await message.channel.send(f"Unblacklist failed: {e}")

        elif keyword in {"unnick", "unlocknick"}:
            if not is_admin:
                return await message.channel.send("No permission.")
            if not target:
                return await message.channel.send("Mention a user to unlock nick.")

            db = load_nick_db()
            db.setdefault("locked", {})
            db["locked"].pop(str(target.id), None)
            save_nick_db(db)

            try:
                await target.edit(nick=None)
                await message.channel.send("Nick unlocked.")
            except Exception as e:
                await message.channel.send(f"Nick unlock failed: {e}")

        elif keyword in {"nick", "locknick"}:
            if not is_admin:
                return await message.channel.send("No permission.")
            if not target:
                return await message.channel.send("Mention a user to lock nick.")

            new_nick = trigger["extra"] or "User"
            db = load_nick_db()
            db.setdefault("locked", {})
            db["locked"][str(target.id)] = new_nick
            save_nick_db(db)

            try:
                await target.edit(nick=new_nick)
                await message.channel.send(f"Nick locked as `{new_nick}`")
            except Exception as e:
                await message.channel.send(f"Nick lock failed: {e}")

        elif keyword == "mute":
            if not is_mod:
                return await message.channel.send("No permission.")
            if not target:
                return await message.channel.send("Mention a user to mute.")

            try:
                duration = self.parse_duration(trigger["main"])
                await target.timeout(discord.utils.utcnow() + duration, reason=reason)
                await message.channel.send(f"Muted {target} for {duration}")
            except Exception as e:
                await message.channel.send(f"Mute failed: {e}")

        elif keyword == "unmute":
            if not is_mod:
                return await message.channel.send("No permission.")
            if not target:
                return await message.channel.send("Mention a user to unmute.")

            try:
                await target.timeout(None, reason=reason)
                await message.channel.send(f"Unmuted {target}")
            except Exception as e:
                await message.channel.send(f"Unmute failed: {e}")

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
