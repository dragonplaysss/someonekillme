import datetime
import re
import time

import discord
from discord.ext import commands


INVITE_REGEX = re.compile(
    r"(discord\.gg|discord\.com/invite)"
)


class AntiRaid(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.spam_tracker = {}
        self.duplicate_tracker = {}

    async def punish(self, message, reason):
        try:
            await message.delete()

            await message.author.timeout(
                discord.utils.utcnow()
                + datetime.timedelta(minutes=10),
                reason=reason,
            )

            await message.channel.send(
                f"{message.author.mention} muted • {reason}",
                delete_after=5,
            )

        except Exception:
            pass

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot or not message.guild:
            return

        content = message.content.strip()

        if not content:
            return

        now = time.time()

        # =========================
        # MESSAGE SPAM
        # =========================

        user_data = self.spam_tracker.setdefault(
            message.author.id,
            []
        )

        user_data.append(now)

        user_data[:] = [
            t for t in user_data
            if now - t < 5
        ]

        if len(user_data) >= 7:
            return await self.punish(
                message,
                "Spam detected"
            )

        # =========================
        # MASS MENTION
        # =========================

        if len(message.mentions) >= 5:
            return await self.punish(
                message,
                "Mass mention spam"
            )

        # =========================
        # INVITE LINKS
        # =========================

        if INVITE_REGEX.search(content.lower()):
            try:
                await message.delete()

                await message.channel.send(
                    f"{message.author.mention} invite links are not allowed.",
                    delete_after=5,
                )

            except Exception:
                pass

            return

        # =========================
        # CAPS SPAM
        # =========================

        letters = [
            c for c in content
            if c.isalpha()
        ]

        if (
            len(letters) >= 15
            and sum(c.isupper() for c in letters)
            / len(letters)
            > 0.7
        ):
            try:
                await message.delete()

                await message.channel.send(
                    f"{message.author.mention} excessive caps detected.",
                    delete_after=5,
                )

            except Exception:
                pass

            return

        # =========================
        # DUPLICATE MESSAGE SPAM
        # =========================

        dupes = self.duplicate_tracker.setdefault(
            message.author.id,
            []
        )

        dupes.append((content.lower(), now))

        dupes[:] = [
            x for x in dupes
            if now - x[1] < 15
        ]

        same_count = sum(
            1
            for msg, _ in dupes
            if msg == content.lower()
        )

        if same_count >= 4:
            return await self.punish(
                message,
                "Duplicate message spam"
            )

        # =========================
        # EMOJI SPAM
        # =========================

        emoji_count = len(
            re.findall(
                r"<a?:\w+:\d+>|[\U00010000-\U0010ffff]",
                content
            )
        )

        if emoji_count >= 10:
            try:
                await message.delete()

                await message.channel.send(
                    f"{message.author.mention} emoji spam detected.",
                    delete_after=5,
                )

            except Exception:
                pass


async def setup(bot):
    await bot.add_cog(AntiRaid(bot))