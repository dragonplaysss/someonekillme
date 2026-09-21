from __future__ import annotations

import datetime
import re
import time
from collections import defaultdict, deque

import discord
from discord.ext import commands

from cogs.core.authz import DangerousActionRequest, authorize_dangerous_action
from cogs.core.responses import response_engine
from cogs.logger import add_log, current_time
from cogs.server_config import get_guild_config, is_mod


SCAM_RE = re.compile(
    r"(discord(?:\.gg|\.com\/gift)|free\s+nitro|steamcommunity\.com\/gift|airdrop)",
    re.IGNORECASE,
)
INVITE_RE = re.compile(r"(?:discord(?:\.gg|\.com\/invite)\/)[A-Za-z0-9-]+", re.IGNORECASE)


class AutoMod(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._messages = defaultdict(deque)
        self._joins = defaultdict(deque)

    def _module_active(self, guild) -> bool:
        config = get_guild_config(guild.id)
        return config.get("enabled") and (config.get("modules") or {}).get("moderation") != "disabled"

    def _prune(self, bucket: deque, window: float):
        now = time.monotonic()
        while bucket and now - bucket[0] > window:
            bucket.popleft()
        return now

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if not member.guild or not self._module_active(member.guild):
            return
        bucket = self._joins[member.guild.id]
        now = self._prune(bucket, 10)
        bucket.append(now)
        if len(bucket) < 8:
            return
        add_log(
            member.guild.id,
            {"type": "raid_protection", "time": current_time(), "joins": len(bucket)},
        )
        anti_nuke = self.bot.get_cog("AntiNuke")
        if anti_nuke:
            await anti_nuke._send_alert(
                member.guild,
                "Raid Watch",
                "A surge of arrivals was noted. Shorekeeper is watching the gate.",
            )

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if not message.guild or message.author.bot or not self._module_active(message.guild):
            return
        if is_mod(message.author):
            return
        key = (message.guild.id, message.author.id)
        bucket = self._messages[key]
        now = self._prune(bucket, 5)
        bucket.append(now)
        content = message.content or ""
        if len(bucket) >= 6:
            try:
                await message.delete()
            except (discord.Forbidden, discord.HTTPException):
                return
            await self._maybe_timeout(message, "anti-spam")
            return
        if SCAM_RE.search(content) or (INVITE_RE.search(content) and "discord.gg/" in content.lower()):
            try:
                await message.delete()
            except (discord.Forbidden, discord.HTTPException):
                return
            add_log(
                message.guild.id,
                {
                    "type": "anti_link",
                    "time": current_time(),
                    "author_id": message.author.id,
                    "channel_id": message.channel.id,
                },
            )
            await message.channel.send(
                embed=response_engine.warning("Link Intercepted", "That message was set aside. The shore does not carry bait."),
                delete_after=6,
            )

    async def _maybe_timeout(self, message, reason: str):
        target = message.author
        if not isinstance(target, discord.Member):
            return
        decision = authorize_dangerous_action(
            DangerousActionRequest(
                guild_config=get_guild_config(message.guild.id),
                module="moderation",
                actor=message.guild.me,
                bot_member=message.guild.me,
                target_member=target,
                target_role=None,
                actor_authorized=True,
                required_bot_permissions=("moderate_members",),
                required_actor_permissions=(),
                security_policy_allowed=True,
                security_action="automod_timeout",
            )
        )
        if not decision.allowed:
            return
        try:
            await target.timeout(discord.utils.utcnow() + datetime.timedelta(minutes=5), reason=f"Shorekeeper {reason}")
        except Exception:
            return


async def setup(bot):
    await bot.add_cog(AutoMod(bot))
