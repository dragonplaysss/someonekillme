import asyncio
import json
import os
from pathlib import Path
import sys

import discord
from discord.ext import commands
from dotenv import load_dotenv

from cogs.module_registry import all_extensions, module_for_slash, visible_slash_commands
from cogs.server_config import get_guild_config, load_config


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
    "mongo_client.py",
    "controls.py",
    "embeds.py",
    "queue.py",
    "trigger_parser.py",
    "server_config.py",
    "module_registry.py",
    "moderation.py",
    "moderation_v2.py",
    "utils.py",
    "views.py",
}


class MyBot(commands.Bot):
    def __init__(self):
        super().__init__(
            command_prefix="!",
            intents=intents,
        )
        self._all_global_app_commands = {}

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

        for cog in all_extensions():
            try:
                await self.load_extension(cog)
                print(f"[LOADED] {cog}")
            except commands.ExtensionAlreadyLoaded:
                pass
            except Exception as e:
                print(f"[FAILED] {cog}: {type(e).__name__}: {e}")

        self.remember_app_commands()
        await self.sync_visible_commands()

    async def on_ready(self):
        print(f"Logged in as {self.user}")

    def remember_app_commands(self):
        self._all_global_app_commands = dict(getattr(self.tree, "_global_commands", {}))

    def _set_visible_tree_commands(self, command_names):
        all_commands = self._all_global_app_commands or dict(getattr(self.tree, "_global_commands", {}))
        visible = {name.lower() for name in command_names}
        filtered = {}
        for key, command in all_commands.items():
            command_name = getattr(command, "name", str(key)).lower()
            module = module_for_slash(command_name)
            if command_name in visible or module == "core":
                filtered[key] = command
        self.tree._global_commands = filtered

    def _restore_tree_commands(self):
        if self._all_global_app_commands:
            self.tree._global_commands = dict(self._all_global_app_commands)

    async def sync_visible_commands(self, guild=None):
        if not self._all_global_app_commands:
            self.remember_app_commands()

        try:
            self._set_visible_tree_commands({"help", "settings", "status", "enablecommands", "disablecommands"})
            await self.tree.sync()
        except Exception as e:
            print(f"[GLOBAL SYNC FAILED] {type(e).__name__}: {e}")
        finally:
            self._restore_tree_commands()

        targets = [guild] if guild else list(self.guilds)
        if not targets:
            configured = load_config().get("guilds", {})
            targets = [discord.Object(id=int(gid)) for gid in configured if gid.isdigit()]

        for target in targets:
            try:
                guild_config = get_guild_config(target.id)
                self._set_visible_tree_commands(visible_slash_commands(guild_config))
                await self.tree.sync(guild=target)
                print(f"[SYNCED] visible commands for guild {target.id}")
            except Exception as e:
                print(f"[GUILD SYNC FAILED] {getattr(target, 'id', '?')}: {type(e).__name__}: {e}")
            finally:
                self._restore_tree_commands()


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
