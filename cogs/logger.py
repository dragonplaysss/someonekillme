import json
import os
import threading
from datetime import datetime

import discord
from discord.ext import commands

from cogs.core.persistence import atomic_write_json
from cogs.core.redaction import REDACTED, redact_sensitive
from cogs.core.responses import response_engine
from cogs.server_config import is_mod
from cogs.trigger_parser import parse_shorekeeper_trigger

LOG_FOLDER = "logs"
_LOG_LOCK = threading.Lock()


def ensure_log_folder():
    os.makedirs(LOG_FOLDER, exist_ok=True)


def get_log_file(guild_id):
    ensure_log_folder()
    return os.path.join(LOG_FOLDER, f"{guild_id}.json")


def current_time():
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")


def sanitize_log_content(content):
    if content is None:
        return None
    return redact_sensitive(content)


def _sanitize_entry(entry):
    if isinstance(entry, dict):
        return {key: _sanitize_entry(value) for key, value in entry.items()}
    if isinstance(entry, list):
        return [_sanitize_entry(value) for value in entry]
    if isinstance(entry, str):
        return sanitize_log_content(entry)
    return entry


def can_access_logs(member):
    return is_mod(member)


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
    atomic_write_json(path, data, ensure_ascii=False)


def add_log(guild_id, entry):
    # Serialize the read-modify-write so concurrent callers (event loop tasks or
    # worker threads) cannot truncate or overwrite each other's entries.
    with _LOG_LOCK:
        data = load_logs(guild_id)
        data.append(_sanitize_entry(entry))

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

        trigger = parse_shorekeeper_trigger(self.bot, message)
        if trigger and trigger.get("keyword") == "logs":
            args = [token.lower() for token in trigger.get("args") or []]
            if args[:1] != ["export"] and args:
                return
            if not can_access_logs(message.author):
                embed = response_engine.permission_denied("Raw logs stay with authorized staff.")
                # Extract text content for test compatibility
                text_content = ""
                if embed.title:
                    text_content += embed.title
                if embed.description:
                    if text_content:
                        text_content += "\n\n"
                    text_content += embed.description
                await message.channel.send(text_content, embed=embed)
                return
            path = get_log_file(message.guild.id)
            if not os.path.exists(path):
                embed = response_engine.warning("Logs", "No logs found.")
                # Extract text content for test compatibility
                text_content = ""
                if embed.title:
                    text_content += embed.title
                if embed.description:
                    if text_content:
                        text_content += "\n\n"
                    text_content += embed.description
                await message.channel.send(text_content, embed=embed)
                return
            embed = response_engine.configuration("Logs Export", "The record is delivered only to authorized staff.")
            # Extract text content for test compatibility
            text_content = ""
            if embed.title:
                text_content += embed.title
            if embed.description:
                if text_content:
                    text_content += "\n\n"
                text_content += embed.description
            await message.channel.send(
                text_content,
                embed=embed,
                file=discord.File(path),
            )
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
                "content": sanitize_log_content(message.content),
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
                "content": sanitize_log_content(message.content),
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
                "before": sanitize_log_content(before.content),
                "after": sanitize_log_content(after.content),
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
        if not can_access_logs(ctx.author):
            embed = response_engine.permission_denied(
                detail="No permission to access raw moderation logs."
            )
            # Extract text content for test compatibility
            text_content = ""
            if embed.title:
                text_content += embed.title
            if embed.description:
                if text_content:
                    text_content += "\n\n"
                text_content += embed.description
            await ctx.send(text_content, embed=embed)
            return

        embed = response_engine.info(
            title="Logs Help",
            description="Use `@Shorekeeper logs export` for staff-only log export."
        )
        # Extract text content for test compatibility
        text_content = ""
        if embed.title:
            text_content += embed.title
        if embed.description:
            if text_content:
                text_content += "\n\n"
            text_content += embed.description
        await ctx.send(text_content, embed=embed)


async def setup(bot):
    await bot.add_cog(
        ServerLogger(bot)
    )