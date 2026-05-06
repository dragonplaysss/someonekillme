import asyncio
import json
import os
from pathlib import Path
import sys

import discord
from discord.ext import commands
from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent
os.chdir(BASE_DIR)
load_dotenv(BASE_DIR / ".env")

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


TOKEN = os.getenv("DISCORD_TOKEN")
LOCK_HANDLE = None

intents = discord.Intents.all()


SKIP_FILES = {
    "__init__.py",
    "controls.py",
    "embeds.py",
    "queue.py",
    "trigger_parser.py",
    "server_config.py",
    "moderation.py",
    "moderation_v2.py",
    "utils.py",
    "views.py",
}

# Loaded via cogs.music package __init__ only (avoids duplicate cogs).
SKIP_EXTENSIONS = {
    "cogs.music.player",
    "cogs.music.setup",
    "cogs.music.wavelink_player",
}


class MyBot(commands.Bot):
    def __init__(self):
        super().__init__(
            command_prefix="!",
            intents=intents,
        )

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

        for root, dirs, files in os.walk(BASE_DIR / "cogs"):
            dirs[:] = sorted(d for d in dirs if d != "__pycache__")
            for file in files:
                if not file.endswith(".py"):
                    continue

                if file in SKIP_FILES:
                    continue

                path = os.path.join(root, file)

                cog = (
                    os.path.relpath(path, BASE_DIR)
                    .replace("\\", ".")
                    .replace("/", ".")
                    .replace(".py", "")
                )

                if cog in SKIP_EXTENSIONS:
                    continue

                try:
                    await self.load_extension(cog)
                    print(f"[LOADED] {cog}")

                except Exception as e:
                    print(
                        f"[FAILED] {cog}: "
                        f"{type(e).__name__}: {e}"
                    )

        try:
            await self.tree.sync()
        except Exception as e:
            print(f"[SYNC FAILED] {type(e).__name__}: {e}")

    async def on_ready(self):
        print(f"Logged in as {self.user}")


async def main():
    if not TOKEN:
        raise RuntimeError(
            "DISCORD_TOKEN is missing. Set it in the environment or in a .env file."
        )

    bot = MyBot()

    await bot.start(TOKEN)


def acquire_instance_lock():
    global LOCK_HANDLE

    lock_path = BASE_DIR / "shorekeeper.lock"
    LOCK_HANDLE = open(lock_path, "w")

    if os.name == "nt":
        import msvcrt

        try:
            msvcrt.locking(LOCK_HANDLE.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            raise RuntimeError("Another Shorekeeper bot process is already running.") from exc
    else:
        import fcntl

        try:
            fcntl.flock(LOCK_HANDLE.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise RuntimeError("Another Shorekeeper bot process is already running.") from exc

    LOCK_HANDLE.write(str(os.getpid()))
    LOCK_HANDLE.flush()


if __name__ == "__main__":
    acquire_instance_lock()
    asyncio.run(main())
