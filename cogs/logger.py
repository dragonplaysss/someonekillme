import json
import os
from datetime import datetime

import discord
from discord.ext import commands


LOG_FOLDER = "logs"


def ensure_log_folder():
    os.makedirs(LOG_FOLDER, exist_ok=True)


def get_log_file(guild_id):
    ensure_log_folder()
    return os.path.join(LOG_FOLDER, f"{guild_id}.json")


def current_time():
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")


def load_logs(guild_id):
    path = get_log_file(guild_id)

    if not os.path.exists(path):
        return []

    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    except Exception:
        return []


def save_logs(guild_id, data):
    path = get_log_file(guild_id)

    with open(path, "w", encoding="utf-8") as f:
        json.dump(
            data,
            f,
            indent=4,
            ensure_ascii=False
        )


def add_log(guild_id, entry):
    data = load_logs(guild_id)

    data.append(entry)

    # keep only latest 10000 entries
    if len(data) > 10000:
        data = data[-10000:]

    save_logs(guild_id, data)


class ServerLogger(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # =========================
    # MESSAGE EVENTS
    # =========================

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot:
            return

        if not message.guild:
            return

        add_log(
            message.guild.id,
            {
                "type": "message",
                "time": current_time(),
                "author": str(message.author),
                "author_id": message.author.id,
                "channel": str(message.channel),
                "channel_id": message.channel.id,
                "content": message.content,
            }
        )

    @commands.Cog.listener()
    async def on_message_delete(self, message):
        if message.author.bot:
            return

        if not message.guild:
            return

        add_log(
            message.guild.id,
            {
                "type": "message_delete",
                "time": current_time(),
                "author": str(message.author),
                "author_id": message.author.id,
                "channel": str(message.channel),
                "channel_id": message.channel.id,
                "content": message.content,
            }
        )

    @commands.Cog.listener()
    async def on_message_edit(self, before, after):
        if before.author.bot:
            return

        if not before.guild:
            return

        if before.content == after.content:
            return

        add_log(
            before.guild.id,
            {
                "type": "message_edit",
                "time": current_time(),
                "author": str(before.author),
                "author_id": before.author.id,
                "channel": str(before.channel),
                "channel_id": before.channel.id,
                "before": before.content,
                "after": after.content,
            }
        )

    # =========================
    # MEMBER EVENTS
    # =========================

    @commands.Cog.listener()
    async def on_member_join(self, member):
        add_log(
            member.guild.id,
            {
                "type": "member_join",
                "time": current_time(),
                "member": str(member),
                "member_id": member.id,
            }
        )

    @commands.Cog.listener()
    async def on_member_remove(self, member):
        add_log(
            member.guild.id,
            {
                "type": "member_leave",
                "time": current_time(),
                "member": str(member),
                "member_id": member.id,
            }
        )

    @commands.Cog.listener()
    async def on_member_ban(self, guild, user):
        add_log(
            guild.id,
            {
                "type": "member_ban",
                "time": current_time(),
                "user": str(user),
                "user_id": user.id,
            }
        )

    @commands.Cog.listener()
    async def on_member_unban(self, guild, user):
        add_log(
            guild.id,
            {
                "type": "member_unban",
                "time": current_time(),
                "user": str(user),
                "user_id": user.id,
            }
        )

    # =========================
    # VOICE EVENTS
    # =========================

    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member,
        before,
        after
    ):
        if before.channel == after.channel:
            return

        add_log(
            member.guild.id,
            {
                "type": "voice_update",
                "time": current_time(),
                "member": str(member),
                "member_id": member.id,
                "before": (
                    str(before.channel)
                    if before.channel
                    else None
                ),
                "after": (
                    str(after.channel)
                    if after.channel
                    else None
                ),
            }
        )

    # =========================
    # CHANNEL EVENTS
    # =========================

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel):
        add_log(
            channel.guild.id,
            {
                "type": "channel_create",
                "time": current_time(),
                "channel": str(channel),
                "channel_id": channel.id,
            }
        )

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel):
        add_log(
            channel.guild.id,
            {
                "type": "channel_delete",
                "time": current_time(),
                "channel": str(channel),
                "channel_id": channel.id,
            }
        )

    # =========================
    # ROLE EVENTS
    # =========================

    @commands.Cog.listener()
    async def on_guild_role_create(self, role):
        add_log(
            role.guild.id,
            {
                "type": "role_create",
                "time": current_time(),
                "role": role.name,
                "role_id": role.id,
            }
        )

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role):
        add_log(
            role.guild.id,
            {
                "type": "role_delete",
                "time": current_time(),
                "role": role.name,
                "role_id": role.id,
            }
        )

    # =========================
    # COMMAND
    # =========================

    @commands.command()
    async def logs(self, ctx):
        path = get_log_file(ctx.guild.id)

        if not os.path.exists(path):
            await ctx.send("No logs found.")
            return

        await ctx.send(
            file=discord.File(path)
        )


async def setup(bot):
    await bot.add_cog(
        ServerLogger(bot)
    )