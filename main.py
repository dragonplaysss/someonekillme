import asyncio
import json
import os
from pathlib import Path
import sys

import discord
from discord.ext import commands
from dotenv import load_dotenv

from cogs.module_registry import MINECRAFT_GUILD_ID, all_extensions, module_for_slash, slash_allowed_in_guild, visible_slash_commands
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
        self._all_app_commands = []
        self._guild_app_commands = {}
        self._startup_synced = False
        self.slash_health = {
            "registered": 0,
            "visible": 0,
            "synced": 0,
        }

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

    async def on_ready(self):
        print(f"Logged in as {self.user}")
        if not self._startup_synced:
            self._startup_synced = True
            await self.sync_visible_commands(reason="startup")

    def remember_app_commands(self):
        configured = load_config().get("guilds", {})
        guild_ids = {int(gid) for gid in configured if str(gid).isdigit()}
        guild_ids.add(MINECRAFT_GUILD_ID)
        for command in self.tree.get_commands():
            for guild_id in getattr(command, "_guild_ids", None) or []:
                guild_ids.add(int(guild_id))

        self._all_app_commands = list(self.tree.get_commands())
        self._guild_app_commands = {}
        for guild_id in sorted(guild_ids):
            guild = discord.Object(id=guild_id)
            self._guild_app_commands[guild_id] = list(self.tree.get_commands(guild=guild))

        all_known = self._all_known_commands()
        self.slash_health["registered"] = len(all_known)
        print("[SLASH REGISTERED]")
        for command in all_known:
            print(self._command_label(command))

    def _all_known_commands(self, guild_id=None):
        commands_by_name = {}
        for command in self._all_app_commands:
            commands_by_name[getattr(command, "name", "").lower()] = command
        if guild_id is not None:
            for command in self._guild_app_commands.get(int(guild_id), []):
                commands_by_name[getattr(command, "name", "").lower()] = command
        else:
            for commands_for_guild in self._guild_app_commands.values():
                for command in commands_for_guild:
                    commands_by_name.setdefault(getattr(command, "name", "").lower(), command)
        return list(commands_by_name.values())

    def _command_label(self, command):
        name = getattr(command, "name", str(command))
        children = getattr(command, "commands", None)
        if children:
            child_names = ", ".join(child.name for child in children)
            return f"{name} ({child_names})"
        return name

    def _set_visible_tree_commands(self, command_names, guild_id=None):
        if not self._all_app_commands and not self._guild_app_commands:
            self.remember_app_commands()

        selected = self._select_visible_commands(command_names, guild_id=guild_id)

        self.tree.clear_commands(guild=None)
        for command in selected:
            self.tree.add_command(command)

        visible_names = [command.name for command in selected]
        self.slash_health["visible"] = len(visible_names)
        print("[SLASH VISIBLE]")
        for command in selected:
            print(self._command_label(command))
        return visible_names

    def _select_visible_commands(self, command_names, guild_id=None):
        requested = {name.lower() for name in command_names}
        core = {
            "help",
            "settings",
            "status",
            "enablecommands",
            "disablecommands",
            "addserveradmin",
            "removeserveradmin",
            "serveradmins",
        }
        visible = set(requested or core)
        selected = []
        for command in self._all_known_commands(guild_id=guild_id):
            command_name = getattr(command, "name", "").lower()
            module = module_for_slash(command_name)
            if not slash_allowed_in_guild(command_name, guild_id):
                continue
            if command_name in visible or module == "core":
                selected.append(command)

        if not selected:
            visible = set(core)
            selected = [
                command
                for command in self._all_known_commands(guild_id=guild_id)
                if getattr(command, "name", "").lower() in visible
            ]

        return selected

    def _restore_tree_commands(self):
        self.tree.clear_commands(guild=None)
        for command in self._all_app_commands:
            if slash_allowed_in_guild(getattr(command, "name", "").lower(), None):
                self.tree.add_command(command)

    async def sync_visible_commands(self, guild=None, reason="manual"):
        if not self._all_app_commands and not self._guild_app_commands:
            self.remember_app_commands()

        targets = [guild] if guild else list(self.guilds)
        if not targets:
            configured = load_config().get("guilds", {})
            target_ids = {int(gid) for gid in configured if gid.isdigit()}
            target_ids.add(MINECRAFT_GUILD_ID)
            targets = [discord.Object(id=gid) for gid in sorted(target_ids)]

        if not targets:
            targets = [None]

        total_synced = 0
        try:
            if any(target is not None for target in targets):
                self.tree.clear_commands(guild=None)
                cleared = await self.tree.sync()
                self._log_synced_commands(cleared, "global", f"{reason} clear stale globals", [])
                self._restore_tree_commands()

            for target in targets:
                if target is None:
                    visible_names = self._set_visible_tree_commands(
                        {
                            "help",
                            "settings",
                            "status",
                            "enablecommands",
                            "disablecommands",
                            "addserveradmin",
                            "removeserveradmin",
                            "serveradmins",
                        }
                    )
                    synced = await self.tree.sync()
                    total_synced += len(synced)
                    self._log_synced_commands(synced, "global", reason, visible_names)
                    continue

                guild_config = get_guild_config(target.id)
                selected = self._select_visible_commands(
                    visible_slash_commands(guild_config, guild_id=target.id),
                    guild_id=target.id,
                )
                visible_names = [command.name for command in selected]
                self.slash_health["visible"] = len(visible_names)
                print("[SLASH VISIBLE]")
                for command in selected:
                    print(self._command_label(command))
                self.tree.clear_commands(guild=target)
                for command in selected:
                    self.tree.add_command(command, guild=target)
                synced = await self.tree.sync(guild=target)
                total_synced += len(synced)
                self._log_synced_commands(synced, f"guild {target.id}", reason, visible_names)
        except Exception as e:
            print(f"[SLASH SYNC FAILED] {type(e).__name__}: {e}")
        finally:
            self.slash_health["synced"] = total_synced
            print(
                "[SLASH HEALTH] "
                f"registered={self.slash_health['registered']} "
                f"visible={self.slash_health['visible']} "
                f"synced={self.slash_health['synced']}"
            )
            self._restore_tree_commands()

        return total_synced

    def _log_synced_commands(self, synced, scope, reason, visible_names):
        print(f"[SLASH SYNC] scope={scope} reason={reason} visible={len(visible_names)} synced={len(synced)}")
        print("[SLASH SYNCED]")
        for command in synced:
            print(self._command_label(command))


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
