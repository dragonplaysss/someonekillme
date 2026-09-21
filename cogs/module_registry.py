CORE_MODULE = "core"
MINECRAFT_GUILD_ID = 1459184432954212477
ROBLOX_AUTH_GUILD_ID = 1528882609042755584
MODULE_STATES = {"active", "hidden", "disabled", "debug"}

RETIRED_MODULES = {
    "applications",
    "ff",
    "divisions",
    "tickets",
    "vibe",
    "minecraft",
}

COMMAND_ALIASES = {
    "commands": "shorehelp",
    "cmds": "shorehelp",
    "help": "shorehelp",
    "sync": "resync",
    "timeout": "mute",
    "clean": "purge",
    "clear": "purge",
    "addrole": "giverole",
    "remrole": "removerole",
    "av": "avatar",
    "server": "serverinfo",
    "user": "userinfo",
    "me": "whoami",
    "cfg": "config",
    "bark": "barklock",
    "unbark": "unbarklock",
    "uwu": "uwulock",
    "unuwu": "unuwulock",
    "away": "afk",
    "brb": "afk",
}

MODULES = {
    "core": {
        "extension": "cogs.module_manager",
        "slash": [
            "help",
            "settings",
            "status",
            "enablecommands",
            "disablecommands",
            "addserveradmin",
            "removeserveradmin",
            "serveradmins",
            "snipeconfig",
        ],
        "mention": [
            "health",
            "module",
            "update",
            "resync",
            "shorehelp",
            "ping",
            "whoami",
            "config",
            "showconfig",
            "verifyconfig",
            "guild",
            "activateguild",
            "deactivateguild",
            "guildstatus",
            "lockdown",
        ],
    },
    "applications": {
        "extension": None,
        "slash": [],
        "mention": [],
        "default_state": "disabled",
        "retired": True,
    },
    "ff": {
        "extension": None,
        "slash": [],
        "mention": [],
        "default_state": "disabled",
        "retired": True,
    },
    "divisions": {
        "extension": None,
        "slash": [],
        "mention": [],
        "default_state": "disabled",
        "retired": True,
    },
    "tickets": {
        "extensions": [],
        "slash": [],
        "mention": [],
        "default_state": "disabled",
        "retired": True,
    },
    "welcome": {
        "extension": "cogs.welcome",
        "slash": ["setupwelcome", "setupgoodbye", "setwelcomegif", "setgoodbyegif"],
        "mention": [],
    },
    "embed": {
        "extension": "cogs.embed_webhook",
        "slash": ["embed", "webhook"],
        "mention": [],
    },
    "moderation": {
        "extensions": [
            "cogs.moderation.moderation_core",
            "cogs.moderation.moderation_panel",
            "cogs.moderation.nicklock",
            "cogs.moderation.role_tools",
            "cogs.moderation.seal",
            "cogs.moderation.automod",
        ],
        "slash": ["modpanel"],
        "mention": [
            "modtest",
            "ban",
            "kick",
            "unban",
            "mute",
            "unmute",
            "untimeout",
            "warn",
            "purge",
            "clear",
            "modpanel",
            "locknick",
            "unlocknick",
            "nicklocks",
            "giverole",
            "removerole",
            "seal",
            "unseal",
            "lock",
            "unlock",
            "slowmode",
            "case",
            "cases",
        ],
    },
    "roles": {
        "extension": "cogs.roles",
        "slash": [],
        "mention": [],
    },
    "verify": {
        "extension": "cogs.verify",
        "slash": [],
        "mention": ["verify"],
    },
    "misc": {
        "extension": "cogs.misc_tools",
        "slash": [],
        "mention": [
            "avatar",
            "serverinfo",
            "userinfo",
            "warns",
            "setverify",
            "owners",
            "setowner",
            "force",
            "barklock",
            "unbarklock",
            "uwulock",
            "unuwulock",
            "lockstatus",
            "afk",
        ],
    },
    "vibe": {
        "extension": None,
        "slash": [],
        "mention": [],
        "default_state": "disabled",
        "retired": True,
    },
    "logger": {
        "extension": "cogs.logger",
        "slash": [],
        "mention": ["logs"],
    },
    "anti_nuke": {
        "extension": "cogs.anti_nuke",
        "slash": [],
        "mention": ["antinuke"],
        "default_state": "disabled",
    },
    "minecraft": {
        "extension": None,
        "slash": [],
        "mention": [],
        "default_state": "disabled",
        "retired": True,
        "guild_ids": [MINECRAFT_GUILD_ID],
    },
    "roblox_auth": {
        "extension": "cogs.roblox_auth",
        "slash": [
            "rbxmanagerrole",
            "rbxadd",
            "rbxedit",
            "rbxremove",
            "rbxlist",
            "rbxinfo",
            "approveauth",
            "rejectauth",
            "revokeauth",
            "activeapprovals",
            "rbxauthguild",
        ],
        "mention": ["robloxauth", "rbxrequest", "approveauth"],
        "default_state": "active",
    },
    "roblox_snipe": {
        "extension": "cogs.roblox_snipe",
        "slash": ["snipe"],
        "mention": ["snipe"],
        "default_state": "disabled",
    },
}


def normalize_module_name(name):
    lowered = (name or "").strip().lower()
    aliases = {
        "application": "applications",
        "apps": "applications",
        "fastflags": "ff",
        "fastflag": "ff",
        "ffcheck": "ff",
        "webhooks": "embed",
        "embeds": "embed",
        "mod": "moderation",
        "roblox": "roblox_auth",
    }
    return aliases.get(lowered, lowered)


def normalize_state(state):
    lowered = (state or "active").strip().lower()
    if lowered == "enabled":
        return "active"
    if lowered not in MODULE_STATES:
        return "active"
    return lowered


def is_retired_module(module):
    meta = MODULES.get(module, {})
    return bool(meta.get("retired")) or module in RETIRED_MODULES


def get_module_state(guild_config, module):
    if module == CORE_MODULE:
        return "active"
    if is_retired_module(module):
        return "disabled"
    states = (guild_config or {}).get("modules", {})
    if module in states:
        return normalize_state(states.get(module))
    meta = MODULES.get(module, {})
    if meta.get("default_state"):
        return normalize_state(meta["default_state"])
    return "hidden" if meta.get("slash") else "active"


def set_module_state(guild_config, module, state):
    guild_config.setdefault("modules", {})[module] = normalize_state(state)


def all_extensions():
    seen = []
    for module, meta in MODULES.items():
        if is_retired_module(module):
            continue
        extensions = meta.get("extensions") or [meta.get("extension")]
        for extension in extensions:
            if extension and extension not in seen:
                seen.append(extension)
    return seen


def module_extensions(module):
    meta = MODULES.get(module, {})
    return [extension for extension in (meta.get("extensions") or [meta.get("extension")]) if extension]


def module_for_extension(extension):
    for module in module_names():
        if extension in module_extensions(module):
            return module
    return None


def restricted_guild_ids():
    guild_ids = set()
    for meta in MODULES.values():
        guild_ids.update(int(guild_id) for guild_id in meta.get("guild_ids", []))
    return guild_ids


def module_allowed_in_guild(module, guild_id):
    meta = MODULES.get(module, {})
    guild_ids = {int(guild_id) for guild_id in meta.get("guild_ids", [])}
    if not guild_ids:
        return True
    return guild_id in guild_ids


def module_for_slash(command_name):
    command_name = (command_name or "").lower()
    for module, meta in MODULES.items():
        if command_name in {item.lower() for item in meta.get("slash", [])}:
            return module
    return "misc"


def slash_commands_for_module(module):
    meta = MODULES.get(module, {})
    return {name.lower() for name in meta.get("slash", [])}


def slash_allowed_in_guild(command_name, guild_id):
    module = module_for_slash(command_name)
    return module_allowed_in_guild(module, guild_id)


def module_for_mention(keyword):
    keyword = normalize_mention_keyword(keyword)
    for module, meta in MODULES.items():
        if keyword in {item.lower() for item in meta.get("mention", [])}:
            return module
    return None


def normalize_mention_keyword(keyword):
    lowered = (keyword or "").strip().lower()
    return COMMAND_ALIASES.get(lowered, lowered)


def aliases_for_mention(command_name):
    command_name = (command_name or "").strip().lower()
    return sorted(alias for alias, canonical in COMMAND_ALIASES.items() if canonical == command_name)


def mention_command_label(command_name):
    aliases = aliases_for_mention(command_name)
    if aliases:
        return f"`{command_name}` ({', '.join(f'`{alias}`' for alias in aliases)})"
    return f"`{command_name}`"


def mention_command_list(command_names):
    return ", ".join(mention_command_label(name) for name in command_names) or "None"


def visible_slash_commands(guild_config, guild_id=None):
    from cogs.core.permissions import guild_enabled

    visible = {CORE_MODULE}
    if not guild_enabled(guild_config):
        return visible
    for module, meta in MODULES.items():
        if module == CORE_MODULE:
            continue
        if is_retired_module(module):
            continue
        if not module_allowed_in_guild(module, guild_id):
            continue
        if get_module_state(guild_config, module) in {"active", "debug"}:
            visible.add(module)
    return visible


def module_names():
    return sorted(MODULES)
