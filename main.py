import asyncio
import json
import os
import sys

import discord
from discord.ext import commands
from dotenv import load_dotenv


load_dotenv()

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

TOKEN = os.getenv("DISCORD_TOKEN")
intents = discord.Intents.all()


class MyBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=intents)

    def load_db(self):
        try:
            with open("database.json", "r") as f:
                return json.load(f)
        except Exception:
            return {}

    def save_db(self, data):
        with open("database.json", "w") as f:
            json.dump(data, f, indent=4)

    async def setup_hook(self):
        print("Loading cogs...")

        skip_root = {
            "moderation.py",
            "moderation_v2.py",
            "trigger_parser.py",
            "server_config.py",
        }
        for filename in os.listdir("./cogs"):
            if filename.endswith(".py") and filename != "__init__.py" and filename not in skip_root:
                try:
                    await self.load_extension(f"cogs.{filename[:-3]}")
                    print(f"Loaded {filename}")
                except Exception as e:
                    print(f"Failed to load {filename}: {type(e).__name__}: {e}")

        if os.path.exists("./cogs/gank"):
            for filename in os.listdir("./cogs/gank"):
                if filename.endswith(".py") and filename != "__init__.py":
                    try:
                        await self.load_extension(f"cogs.gank.{filename[:-3]}")
                        print(f"Loaded gank {filename}")
                    except Exception as e:
                        print(f"Failed to load gank {filename}: {type(e).__name__}: {e}")

        try:
            await self.load_extension("cogs.music")
            print("Loaded music package")
        except Exception as e:
            print(f"Failed to load music package: {type(e).__name__}: {e}")

        try:
            await self.load_extension("cogs.tracker.tracker")
            print("Loaded tracker system")
        except Exception as e:
            print(f"Failed to load tracker: {type(e).__name__}: {e}")

        try:
            await self.load_extension("cogs.moderation")
            print("Loaded moderation package")
        except Exception as e:
            print(f"Failed to load moderation package: {type(e).__name__}: {e}")

        guild = discord.Object(id=1489351990705131571)
        self.tree.copy_global_to(guild=guild)
        await self.tree.sync(guild=guild)
        print("Slash commands synced")

    async def on_ready(self):
        print(f"Logged in as {self.user}")


async def main():
    bot = MyBot()
    await bot.start(TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
