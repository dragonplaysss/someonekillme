import json
import os
import secrets
import time

import discord
from discord.ext import commands

from cogs.server_config import get_channel_id, is_admin
from cogs.trigger_parser import parse_shorekeeper_trigger


DATA_PATH = "config/applications.json"


def _load():
    if not os.path.exists(DATA_PATH):
        return {"guilds": {}}
    try:
        with open(DATA_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {"guilds": {}}
    except json.JSONDecodeError:
        return {"guilds": {}}


def _save(data):
    os.makedirs(os.path.dirname(DATA_PATH), exist_ok=True)
    with open(DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)


def _guild_data(data, guild_id):
    guilds = data.setdefault("guilds", {})
    return guilds.setdefault(str(guild_id), {"active": None, "submissions": []})


class Applications(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        trigger = parse_shorekeeper_trigger(self.bot, message)
        if not trigger or trigger["keyword"] != "application":
            return
        args = trigger["args"]
        action = args[0].lower() if args else ""
        if action == "create":
            return await self._create(message, trigger)
        if action == "close":
            return await self._close(message)
        if action == "verify":
            return await self._verify(message, trigger)
        if action == "review":
            return await self._review(message)
        await message.channel.send(
            "Use `application create ; form_url [token]`, `application verify [token]`, "
            "`application review`, or `application close`."
        )

    async def _create(self, message, trigger):
        if not is_admin(message.author):
            return await message.channel.send("No permission.")
        parts = (trigger["extra"] or "").split()
        if not parts:
            return await message.channel.send("Use `application create ; https://forms.gle/... [token]`.")
        form_url = parts[0].strip()
        if not form_url.startswith(("http://", "https://")):
            return await message.channel.send("Application form must be a valid URL.")
        token = parts[1].strip() if len(parts) > 1 else secrets.token_urlsafe(6)

        data = _load()
        guild_data = _guild_data(data, message.guild.id)
        guild_data["active"] = {
            "form_url": form_url,
            "token": token,
            "created_by": message.author.id,
            "created_at": int(time.time()),
            "review_channel_id": message.channel.id,
            "open": True,
        }
        _save(data)

        embed = discord.Embed(title="Applications Open", color=0x57F287)
        embed.description = "Applicants can request the form and verify after submitting."
        embed.add_field(name="Form", value=form_url, inline=False)
        embed.add_field(name="Verification Token", value=f"`{token}`", inline=False)
        await message.channel.send(embed=embed)

    async def _close(self, message):
        if not is_admin(message.author):
            return await message.channel.send("No permission.")
        data = _load()
        guild_data = _guild_data(data, message.guild.id)
        if not guild_data.get("active"):
            return await message.channel.send("No application is currently open.")
        guild_data["active"]["open"] = False
        guild_data["active"]["closed_at"] = int(time.time())
        guild_data["active"]["closed_by"] = message.author.id
        _save(data)
        await message.channel.send("Applications closed.")

    async def _verify(self, message, trigger):
        data = _load()
        guild_data = _guild_data(data, message.guild.id)
        active = guild_data.get("active")
        if not active or not active.get("open"):
            return await message.channel.send("Applications are not open.")

        supplied_token = trigger["args"][1] if len(trigger["args"]) > 1 else (trigger["extra"] or "").strip()
        expected_token = active.get("token")
        if expected_token and supplied_token and supplied_token != expected_token:
            return await message.channel.send("Application token did not match.")

        submission = {
            "user_id": message.author.id,
            "verified_at": int(time.time()),
            "message_id": message.id,
            "channel_id": message.channel.id,
            "status": "pending",
        }
        guild_data.setdefault("submissions", []).append(submission)
        _save(data)

        review_channel_id = active.get("review_channel_id") or get_channel_id(message.guild.id, "logging")
        review_channel = message.guild.get_channel(review_channel_id) if review_channel_id else None
        embed = discord.Embed(title="Application Verification", color=0x5865F2)
        embed.add_field(name="Applicant", value=f"{message.author.mention} (`{message.author.id}`)", inline=False)
        embed.add_field(name="Form", value=active.get("form_url", "Not set"), inline=False)
        embed.add_field(name="Submitted", value=discord.utils.format_dt(discord.utils.utcnow(), "R"), inline=True)
        if review_channel:
            await review_channel.send(embed=embed)
        await message.channel.send("Application verified. A reviewer has been notified.")

    async def _review(self, message):
        if not is_admin(message.author):
            return await message.channel.send("No permission.")
        data = _load()
        guild_data = _guild_data(data, message.guild.id)
        submissions = guild_data.get("submissions", [])[-10:]
        active = guild_data.get("active") or {}
        embed = discord.Embed(title="Application Review Panel", color=0xFEE75C)
        embed.add_field(name="Open", value=str(bool(active.get("open"))), inline=True)
        embed.add_field(name="Form", value=active.get("form_url", "Not set"), inline=False)
        if submissions:
            embed.add_field(
                name="Recent Applicants",
                value="\n".join(f"<@{item['user_id']}> - `{item.get('status', 'pending')}`" for item in submissions),
                inline=False,
            )
        else:
            embed.add_field(name="Recent Applicants", value="None", inline=False)
        await message.channel.send(embed=embed)


async def setup(bot):
    await bot.add_cog(Applications(bot))
