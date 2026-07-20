import asyncio
import json
import os
from pathlib import Path
import sys
import traceback

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

from cogs.module_registry import MINECRAFT_GUILD_ID, all_extensions, module_for_slash, slash_allowed_in_guild, visible_slash_commands
from cogs.server_config import get_guild_config, load_config
from cogs.trigger_parser import parse_shorekeeper_trigger


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
intents.message_content = True


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
        self.tree.on_error = self._on_app_command_error

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

        print(
            "[INTENTS] "
            f"members={self.intents.members} "
            f"guild_messages={self.intents.guild_messages} "
            f"message_content={self.intents.message_content} "
            f"guilds={self.intents.guilds}"
        )

        for cog in self.discover_extensions():
            try:
                print(f"[COG SETUP] calling setup() for {cog}")
                await self.load_extension(cog)
                print(f"[LOADED] {cog}")
            except commands.ExtensionAlreadyLoaded:
                pass
            except Exception as e:
                print(f"[FAILED] {cog}: {type(e).__name__}: {e}")
                traceback.print_exc()

        self.remember_app_commands()
        self.audit_loaded_cogs()
        self.audit_command_registry()

    async def on_ready(self):
        print(f"Logged in as {self.user}")
        print(
            "[READY INTENTS] "
            f"message_content={self.intents.message_content}. "
            "If mention commands log empty content, enable Message Content Intent in the Discord Developer Portal too."
        )
        if not self._startup_synced:
            self._startup_synced = True
            await self.sync_visible_commands(reason="startup")

    def discover_extensions(self):
        ordered = []
        for extension in all_extensions():
            if extension not in ordered:
                ordered.append(extension)

        for path in sorted((BASE_DIR / "cogs").rglob("*.py")):
            if path.name in SKIP_FILES:
                continue
            if path.name.startswith("_"):
                continue
            module_path = ".".join(path.relative_to(BASE_DIR).with_suffix("").parts)
            if module_path not in ordered:
                ordered.append(module_path)

        return ordered

    async def on_message(self, message):
        print(
            "[MSG RECEIVED] "
            f"guild={getattr(message.guild, 'id', None)} "
            f"channel={getattr(message.channel, 'id', None)} "
            f"author={getattr(message.author, 'id', None)} "
            f"bot_author={getattr(message.author, 'bot', None)} "
            f"content_len={len(message.content or '')} "
            f"mentions={[getattr(user, 'id', None) for user in getattr(message, 'mentions', [])]}"
        )

        trigger = parse_shorekeeper_trigger(self, message, debug=True)
        if trigger:
            module = trigger.get("module")
            found = self.mention_command_registered(trigger["keyword"])
            print(
                "[MENTION COMMAND FOUND] "
                f"keyword={trigger['raw_keyword']}->{trigger['keyword']} "
                f"module={module or 'unknown'} "
                f"registered={found}"
            )
        elif self.user and self.user.mentioned_in(message):
            print("[MENTION COMMAND STOP] bot was mentioned, but no executable trigger was parsed.")

        await self.process_commands(message)

    async def on_command(self, ctx):
        print(f"[PREFIX COMMAND INVOKED] command={ctx.command.qualified_name} author={ctx.author.id} guild={getattr(ctx.guild, 'id', None)}")

    async def on_command_completion(self, ctx):
        print(f"[PREFIX COMMAND COMPLETED] command={ctx.command.qualified_name} author={ctx.author.id} guild={getattr(ctx.guild, 'id', None)}")

    async def on_command_error(self, ctx, error):
        print(
            f"[PREFIX COMMAND ERROR] command={getattr(ctx.command, 'qualified_name', None)} "
            f"author={getattr(ctx.author, 'id', None)} error={type(error).__name__}: {error}"
        )
        traceback.print_exception(type(error), error, error.__traceback__)

    async def on_error(self, event_method, *args, **kwargs):
        print(f"[DISCORD EVENT ERROR] event={event_method}")
        traceback.print_exc()

    async def _on_app_command_error(self, interaction, error):
        command_name = getattr(getattr(interaction, "command", None), "qualified_name", None)
        print(
            f"[SLASH COMMAND ERROR] command={command_name} "
            f"user={getattr(getattr(interaction, 'user', None), 'id', None)} "
            f"guild={getattr(getattr(interaction, 'guild', None), 'id', None)} "
            f"error={type(error).__name__}: {error}"
        )
        traceback.print_exception(type(error), error, error.__traceback__)
        try:
            if interaction.response.is_done():
                await interaction.followup.send("Command failed. Check bot logs for traceback.", ephemeral=True)
            else:
                await interaction.response.send_message("Command failed. Check bot logs for traceback.", ephemeral=True)
        except Exception:
            traceback.print_exc()

    def mention_command_registered(self, keyword):
        from cogs.module_registry import MODULES, normalize_mention_keyword

        normalized = normalize_mention_keyword(keyword)
        return any(normalized in {item.lower() for item in meta.get("mention", [])} for meta in MODULES.values())

    def audit_loaded_cogs(self):
        print("[COG AUDIT]")
        for name, cog in sorted(self.cogs.items()):
            commands_for_cog = list(cog.get_commands())
            listeners = cog.get_listeners()
            aliases = []
            for command in commands_for_cog:
                aliases.extend(getattr(command, "aliases", []) or [])
            print(
                f"  cog={name} commands={len(commands_for_cog)} "
                f"aliases={aliases or []} "
                f"listeners={[listener_name for listener_name, _ in listeners]}"
            )

    def audit_command_registry(self):
        print("[PREFIX COMMAND REGISTRY]")
        prefix_count = 0
        hybrid_count = 0
        for command in sorted(self.walk_commands(), key=lambda cmd: cmd.qualified_name):
            prefix_count += 1
            if isinstance(command, commands.HybridCommand):
                hybrid_count += 1
            print(
                f"  command={command.qualified_name} "
                f"type={'hybrid' if isinstance(command, commands.HybridCommand) else 'prefix'} "
                f"aliases={getattr(command, 'aliases', []) or []} "
                f"enabled={command.enabled}"
            )
        if prefix_count == 0:
            print("  (none)")
        print(f"[PREFIX COMMAND TOTAL] prefix={prefix_count} hybrid={hybrid_count}")

        print("[SLASH COMMAND REGISTRY]")
        for command in self._all_known_commands():
            self._print_app_command(command)

    def _print_app_command(self, command, parent=None):
        name = f"{parent} {command.name}" if parent else command.name
        print(f"  slash=/{name} type={type(command).__name__}")
        for child in getattr(command, "commands", []) or []:
            self._print_app_command(child, parent=name)

    def _flatten_commands(self, commands):
        groups = []
        standalone = []
        for command in commands:
            children = getattr(command, "commands", None)
            if children:
                groups.append(command)
            else:
                standalone.append(command)
        return groups, standalone

    def remember_app_commands(self):
        configured = load_config().get("guilds", {})
        guild_ids = {int(gid) for gid in configured if str(gid).isdigit()}
        guild_ids.add(MINECRAFT_GUILD_ID)

        self._all_app_commands = list(self.tree.get_commands())
        self._guild_app_commands = {}
        for guild_id in sorted(guild_ids):
            guild = discord.Object(id=guild_id)
            self._guild_app_commands[guild_id] = list(self.tree.get_commands(guild=guild))

        for command in self._all_app_commands:
            for bound_guild_id in getattr(command, "_guild_ids", None) or []:
                guild_ids.add(int(bound_guild_id))
        for commands_for_guild in self._guild_app_commands.values():
            for command in commands_for_guild:
                for bound_guild_id in getattr(command, "_guild_ids", None) or []:
                    guild_ids.add(int(bound_guild_id))
        if guild_ids - set(self._guild_app_commands):
            for guild_id in sorted(guild_ids):
                if guild_id in self._guild_app_commands:
                    continue
                guild = discord.Object(id=guild_id)
                self._guild_app_commands[guild_id] = list(self.tree.get_commands(guild=guild))

        self._log_tree_state("before sync snapshot")

        all_known = self._all_known_commands()
        groups, standalone = self._flatten_commands(all_known)
        self.slash_health["registered"] = len(all_known)
        print("[SLASH REGISTERED]")
        for command in all_known:
            print(f"  {self._command_label(command)}")
        print("Registered command groups:")
        for command in groups:
            print(f"  {self._command_label(command)}")
        print("Registered commands:")
        for command in standalone:
            print(f"  {command.name}")
        if not all_known:
            print("  (none)")
        minecraft_names = {"mc", "mcsetup", "mcverify", "unlinkmc", "mclinkinfo"}
        found_mc = {getattr(command, "name", "").lower() for command in all_known}
        missing_mc = sorted(name for name in minecraft_names if name not in found_mc)
        if missing_mc:
            print(f"[SLASH REGISTERED] WARNING missing minecraft commands: {', '.join(missing_mc)}")
        else:
            print("[SLASH REGISTERED] minecraft commands: mc, mcsetup, mcverify, unlinkmc, mclinkinfo")

        minecraft_guild_cmds = self._guild_app_commands.get(MINECRAFT_GUILD_ID, [])
        print(f"[SLASH REGISTERED] minecraft guild tree count={len(minecraft_guild_cmds)}")
        for command in minecraft_guild_cmds:
            print(f"  guild-tree {self._command_label(command)}")

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

    def _log_tree_state(self, label):
        print(f"[SLASH TREE] {label}")
        global_cmds = list(self.tree.get_commands())
        print(f"  global count={len(global_cmds)} names={', '.join(cmd.name for cmd in global_cmds) or '(none)'}")
        minecraft_guild_cmds = list(self.tree.get_commands(guild=discord.Object(id=MINECRAFT_GUILD_ID)))
        print(
            f"  guild {MINECRAFT_GUILD_ID} count={len(minecraft_guild_cmds)} "
            f"names={', '.join(cmd.name for cmd in minecraft_guild_cmds) or '(none)'}"
        )

    def _set_visible_tree_commands(self, command_names, guild_id=None):
        if not self._all_app_commands and not self._guild_app_commands:
            self.remember_app_commands()

        selected = self._select_visible_commands(command_names, guild_id=guild_id)

        self.tree.clear_commands(guild=None)
        for command in selected:
            self._safe_add_command(command)

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

    def _safe_add_command(self, command, guild=None):
        try:
            if guild is None:
                self.tree.add_command(command)
            else:
                self.tree.add_command(command, guild=guild)
        except Exception:
            copied = command.copy()
            if guild is None:
                self.tree.add_command(copied)
            else:
                self.tree.add_command(copied, guild=guild)

    def _restore_tree_commands(self):
        self.tree.clear_commands(guild=None)
        for command in self._all_app_commands:
            if slash_allowed_in_guild(getattr(command, "name", "").lower(), None):
                self._safe_add_command(command)
        for guild_id, commands in self._guild_app_commands.items():
            guild = discord.Object(id=guild_id)
            self.tree.clear_commands(guild=guild)
            for command in commands:
                if slash_allowed_in_guild(getattr(command, "name", "").lower(), guild_id):
                    self._safe_add_command(command, guild=guild)

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
                    self._safe_add_command(command, guild=target)
                synced = await self.tree.sync(guild=target)
                total_synced += len(synced)
                print(f"Guild sync result: guild={target.id} reason={reason} visible={len(visible_names)} synced={len(synced)}")
                if target.id == MINECRAFT_GUILD_ID:
                    synced_names = {command.name for command in synced}
                    minecraft_names = {"mc", "mcsetup", "mcverify", "unlinkmc", "mclinkinfo"}
                    missing = sorted(minecraft_names - synced_names)
                    if missing:
                        print(f"[SLASH SYNC] WARNING minecraft guild missing synced commands: {', '.join(missing)}")
                    else:
                        print("[SLASH SYNC] minecraft guild commands synced: mc, mcsetup, mcverify, unlinkmc, mclinkinfo")
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
            self._log_tree_state("after sync")
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

    LOCK_HANDLE.seek(0)
    LOCK_HANDLE.truncate()
    LOCK_HANDLE.write(str(os.getpid()))
    LOCK_HANDLE.flush()


if __name__ == "__main__":
    acquire_instance_lock()
    asyncio.run(main())
