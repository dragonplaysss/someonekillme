import datetime
import re
import time

import discord
from discord.ext import commands


BAD_WORDS = {
    "nigger",
    "nigga",
    "faggot",
    "fag",
    "motherfucker",
    "kys",
    "killyourself",
    "cunt",
    "whore",
    "slut",
    "rape",
    "rapist",
    "hitler",
    "nazl",
    "heilhitler",
    "beaner",
    "chink",
    "spic",
    "wetback",
    "coon",
    "dyke",
    "tranny",
    "kkk",
    "negro",
}


def normalize_text(text):
    text = text.lower()

    replacements = {
        "1": "i",
        "!": "i",
        "@": "a",
        "3": "e",
        "$": "s",
        "5": "s",
        "0": "o",
        "7": "t",
        "4": "a",
        "8": "b",
    }

    for old, new in replacements.items():
        text = text.replace(old, new)

    text = re.sub(r"[^a-z]", "", text)

    return text


class AutoMod(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.spam_tracker = {}

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot or not message.guild:
            return

        content = normalize_text(message.content)

        # CHAT FILTER
        if any(word in content for word in BAD_WORDS):
            try:
                await message.delete()

                await message.channel.send(
                    f"{message.author.mention} blocked word detected.",
                    delete_after=5,
                )

            except Exception:
                pass

            return

        # ANTI SPAM
        now = time.time()

        user_data = self.spam_tracker.setdefault(
            message.author.id,
            []
        )

        user_data.append(now)

        user_data[:] = [
            t for t in user_data
            if now - t < 5
        ]

        if len(user_data) >= 8:
            try:
                await message.author.timeout(
                    discord.utils.utcnow()
                    + datetime.timedelta(minutes=5),
                    reason="Anti-spam",
                )

                await message.channel.send(
                    f"{message.author.mention} muted for spam."
                )

            except Exception:
                pass


async def setup(bot):
    await bot.add_cog(AutoMod(bot))