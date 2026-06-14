CORE_MODULE = "core"
MINECRAFT_GUILD_ID = 1459184432954212477
MODULE_STATES = {"active", "hidden", "disabled", "debug"}
VISIBLE_CORE_COMMANDS = {
    "help",
    "settings",
    "status",
    "enablecommands",
    "disablecommands",
    "addserveradmin",
    "removeserveradmin",
    "serveradmins",
}

COMMAND_ALIASES = {
    "commands": "shorehelp",
    "cmds": "shorehelp",
    "sync": "resync",
    "flags": "ffcheck",
    "joindiv": "joindivision",
    "leavediv": "leavedivision",
    "transcript": "transcripttk",
    "close": "closeticket",
    "deltk": "deletetk",
    "addtk": "addtoticket",
    "remtk": "removefromticket",
    "timeout": "mute",
    "clean": "purge",
    "addrole": "giverole",
    "remrole": "removerole",
    "lockdown": "seal",
    "unlock": "unseal",
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
        ],
        "mention": ["health", "module", "update", "resync", "shorehelp", "ping", "whoami", "config", "showconfig", "verifyconfig"],
    },
    "applications": {
        "extension": "cogs.applications",
        "slash": [],
        "mention": ["application"],
        "default_state": "disabled",
    },
    "ff": {
        "extension": "cogs.ff_checker",
        "slash": [],
        "mention": ["ffcheck", "ff"],
        "default_state": "disabled",
    },
    "divisions": {
        "extension": "cogs.divisions",
        "slash": [
            "setupdivisions",
            "removedivision",
            "setupdivisionregistry",
            "setdivisionrequestchannel",
            "diviupdatewbh",
            "divupdatewbh",
            "setdivisionbanner",
            "setdivisioncrest",
            "setmainerrole",
            "enablejoindivisions",
            "disablejoindivisions",
            "equalizedivisions",
        ],
        "mention": ["joindivision", "leavedivision"],
    },
    "tickets": {
        "extensions": ["cogs.tickets", "cogs.ticket_member_tools"],
        "slash": ["ticketpanel"],
        "mention": ["transcripttk", "closeticket", "deletetk", "addtoticket", "removefromticket"],
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
        ],
        "slash": [],
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
        ],
    },
    "roles": {
        "extension": "cogs.roles",
        "slash": [],
        "mention": [],
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
        "extension": "cogs.vibe",
        "slash": [],
        "mention": ["vibe", "ghost"],
    },
    "logger": {
        "extension": "cogs.logger",
        "slash": [],
        "mention": [],
    },
    "minecraft": {
        "extension": "cogs.minecraft_bridge",
        "slash": ["mc", "mcsetup", "mcverify", "unlinkmc", "mclinkinfo"],
        "mention": [],
        "default_state": "active",
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
    }
    return aliases.get(lowered, lowered)


def normalize_state(state):
    lowered = (state or "active").strip().lower()
    if lowered == "enabled":
        return "active"
    if lowered not in MODULE_STATES:
        return "active"
    return lowered


def get_module_state(guild_config, module):
    if module == CORE_MODULE:
        return "active"
    states = guild_config.get("modules", {})
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
    for meta in MODULES.values():
        extensions = meta.get("extensions") or [meta.get("extension")]
        for extension in extensions:
            if extension and extension not in seen:
                seen.append(extension)
    return seen


def module_for_slash(command_name):
    command_name = (command_name or "").lower()
    for module, meta in MODULES.items():
        if command_name in {item.lower() for item in meta.get("slash", [])}:
            return module
    return "misc"


def slash_allowed_in_guild(command_name, guild_id):
    module = module_for_slash(command_name)
    if module != "minecraft":
        return True
    return guild_id == MINECRAFT_GUILD_ID


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
    visible = set(VISIBLE_CORE_COMMANDS)
    for module, meta in MODULES.items():
        if module == CORE_MODULE:
            continue
        if module == "minecraft" and guild_id != MINECRAFT_GUILD_ID:
            continue
        if get_module_state(guild_config, module) in {"active", "debug"}:
            visible.update(meta.get("slash", []))
    return {name.lower() for name in visible}


def module_names():
    return sorted(MODULES)
