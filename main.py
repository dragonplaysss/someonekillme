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

from cogs.module_registry import (
    CORE_MODULE,
    all_extensions,
    module_allowed_in_guild,
    module_for_extension,
    module_for_slash,
    normalize_module_name,
    restricted_guild_ids,
    slash_allowed_in_guild,
    slash_commands_for_module,
    visible_slash_commands,
)
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
    "mod_config.py",
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
        self._audit_slash_duplicates()
        self._audit_slash_module_mapping()

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
        guild_ids.update(restricted_guild_ids())

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
        for guild_id in sorted(restricted_guild_ids()):
            guild_cmds = self._guild_app_commands.get(guild_id, [])
            print(f"[SLASH REGISTERED] restricted guild tree guild={guild_id} count={len(guild_cmds)}")
            for command in guild_cmds:
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

    def _command_module(self, command):
        command_name = getattr(command, "name", "").lower()
        registry_module = module_for_slash(command_name)
        if command_name in slash_commands_for_module(registry_module):
            return registry_module

        callback = getattr(command, "callback", None)
        callback_module = getattr(callback, "__module__", None)
        inferred = module_for_extension(callback_module)
        if inferred:
            return inferred

        binding = getattr(command, "binding", None)
        binding_module = getattr(type(binding), "__module__", None)
        inferred = module_for_extension(binding_module)
        if inferred:
            return inferred

        return registry_module

    def _audit_slash_duplicates(self):
        seen = {}
        duplicates = {}
        for scope, commands_for_scope in [("global", self._all_app_commands)] + [
            (f"guild {guild_id}", commands_for_guild)
            for guild_id, commands_for_guild in sorted(self._guild_app_commands.items())
        ]:
            for command in commands_for_scope:
                command_name = getattr(command, "name", "").lower()
                if command_name in seen:
                    duplicates.setdefault(command_name, []).extend([seen[command_name], scope])
                else:
                    seen[command_name] = scope

        if duplicates:
            print("[SLASH AUDIT] duplicate command names detected")
            for command_name, scopes in sorted(duplicates.items()):
                print(f"  command={command_name} scopes={', '.join(sorted(set(scopes)))}")
        else:
            print("[SLASH AUDIT] duplicate command names: none")

    def _audit_slash_module_mapping(self):
        print("[SLASH AUDIT] command module mapping")
        for command in sorted(self._all_known_commands(), key=lambda item: getattr(item, "name", "")):
            command_name = getattr(command, "name", "").lower()
            module = self._command_module(command)
            exact_registry = command_name in slash_commands_for_module(module)
            print(
                f"  command={command_name} module={module} "
                f"registry_exact={exact_registry} "
                f"callback_module={getattr(getattr(command, 'callback', None), '__module__', None)}"
            )

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
        for guild_id in sorted(restricted_guild_ids()):
            guild_cmds = list(self.tree.get_commands(guild=discord.Object(id=guild_id)))
            print(
                f"  guild {guild_id} count={len(guild_cmds)} "
                f"names={', '.join(cmd.name for cmd in guild_cmds) or '(none)'}"
            )

    def _set_visible_tree_commands(self, enabled_modules, guild_id=None):
        if not self._all_app_commands and not self._guild_app_commands:
            self.remember_app_commands()

        selected = self._select_visible_commands(enabled_modules, guild_id=guild_id)

        self.tree.clear_commands(guild=None)
        for command in selected:
            self._safe_add_command(command)

        visible_names = [command.name for command in selected]
        self.slash_health["visible"] = len(visible_names)
        print("[SLASH VISIBLE]")
        for command in selected:
            print(self._command_label(command))
        return visible_names

    def _select_visible_commands(self, enabled_modules, guild_id=None):
        visible_modules = {normalize_module_name(module) for module in (enabled_modules or [])}
        visible_modules.add(CORE_MODULE)
        selected = []
        print(
            "[SLASH VISIBILITY INPUT] "
            f"guild={guild_id} visible_modules={', '.join(sorted(visible_modules))}"
        )
        for command in self._all_known_commands(guild_id=guild_id):
            command_name = getattr(command, "name", "").lower()
            module = self._command_module(command)
            allowed = module_allowed_in_guild(module, guild_id)
            legacy_allowed = slash_allowed_in_guild(command_name, guild_id)
            if not allowed:
                self._log_visibility_decision(
                    command,
                    guild_id,
                    module,
                    selected=False,
                    reason="guild_not_allowed",
                    allowed=allowed,
                    legacy_allowed=legacy_allowed,
                    visible_modules=visible_modules,
                )
                continue
            if module in visible_modules:
                self._log_visibility_decision(
                    command,
                    guild_id,
                    module,
                    selected=True,
                    reason="module_enabled",
                    allowed=allowed,
                    legacy_allowed=legacy_allowed,
                    visible_modules=visible_modules,
                )
                selected.append(command)
            else:
                self._log_visibility_decision(
                    command,
                    guild_id,
                    module,
                    selected=False,
                    reason="module_not_visible",
                    allowed=allowed,
                    legacy_allowed=legacy_allowed,
                    visible_modules=visible_modules,
                )

        if not selected:
            selected = [
                command
                for command in self._all_known_commands(guild_id=guild_id)
                if self._command_module(command) == CORE_MODULE
            ]

        return selected

    def _log_visibility_decision(self, command, guild_id, module, selected, reason, allowed, legacy_allowed, visible_modules):
        command_name = getattr(command, "name", "").lower()
        print(
            "[SLASH VISIBILITY] "
            f"guild={guild_id} command={command_name} module={module} "
            f"selected={selected} reason={reason} "
            f"slash_allowed={allowed} slash_allowed_in_guild={legacy_allowed} "
            f"visible_modules={', '.join(sorted(visible_modules))}"
        )

    def _safe_add_command(self, command, guild=None):
        try:
            if guild is None:
                self.tree.add_command(command)
            else:
                self.tree.add_command(command, guild=guild)
        except Exception:
            print(
                "[SLASH TREE ADD] copying command after add failure "
                f"command={getattr(command, 'name', command)} guild={getattr(guild, 'id', guild)}"
            )
            copied = command.copy()
            if guild is None:
                self.tree.add_command(copied)
            else:
                self.tree.add_command(copied, guild=guild)

    def _restore_tree_commands(self):
        self.tree.clear_commands(guild=None)
        for command in self._all_app_commands:
            self._safe_add_command(command)
        for guild_id, commands in self._guild_app_commands.items():
            guild = discord.Object(id=guild_id)
            self.tree.clear_commands(guild=guild)
            for command in commands:
                self._safe_add_command(command, guild=guild)

    async def sync_visible_commands(self, guild=None, reason="manual", enabled_modules=None):
        if not self._all_app_commands and not self._guild_app_commands:
            self.remember_app_commands()

        targets = [guild] if guild else list(self.guilds)
        if not targets:
            configured = load_config().get("guilds", {})
            target_ids = {int(gid) for gid in configured if gid.isdigit()}
            target_ids.update(restricted_guild_ids())
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
                    global_modules = enabled_modules if enabled_modules is not None else {CORE_MODULE}
                    selected = self._select_visible_commands(global_modules)
                    visible_names = [command.name for command in selected]
                    self.slash_health["visible"] = len(visible_names)
                    print("[SLASH VISIBLE]")
                    for command in selected:
                        print(self._command_label(command))
                    self.tree.clear_commands(guild=None)
                    for command in selected:
                        self._safe_add_command(command)
                    synced = await self.tree.sync()
                    total_synced += len(synced)
                    self._verify_synced_matches_selected(synced, selected, None)
                    self._log_synced_commands(synced, "global", reason, visible_names)
                    continue

                guild_config = get_guild_config(target.id)
                target_enabled_modules = (
                    enabled_modules
                    if enabled_modules is not None
                    else visible_slash_commands(guild_config, guild_id=target.id)
                )
                print(
                    "[SLASH VISIBILITY MODULES] "
                    f"guild={target.id} modules={', '.join(sorted(target_enabled_modules))}"
                )
                selected = self._select_visible_commands(
                    target_enabled_modules,
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
                self._verify_synced_matches_selected(synced, selected, target.id)
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

    def _verify_synced_matches_selected(self, synced, selected, guild_id):
        selected_names = {getattr(command, "name", "").lower() for command in selected}
        synced_names = {getattr(command, "name", "").lower() for command in synced}
        missing = sorted(selected_names - synced_names)
        extra = sorted(synced_names - selected_names)
        if missing or extra:
            print(
                "[SLASH SYNC VERIFY] mismatch "
                f"guild={guild_id} missing={', '.join(missing) or '(none)'} "
                f"extra={', '.join(extra) or '(none)'}"
            )
        else:
            print(
                "[SLASH SYNC VERIFY] matched "
                f"guild={guild_id} commands={', '.join(sorted(selected_names)) or '(none)'}"
            )


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
