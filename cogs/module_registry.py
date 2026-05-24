CORE_MODULE = "core"
MODULE_STATES = {"active", "hidden", "disabled", "debug"}
VISIBLE_CORE_COMMANDS = {"help", "settings", "status", "enablecommands", "disablecommands"}

MODULES = {
    "core": {
        "extension": "cogs.module_manager",
        "slash": ["help", "settings", "status", "enablecommands", "disablecommands"],
        "mention": ["health", "module", "update", "resync", "shorehelp", "ping", "whoami", "config", "showconfig", "verifyconfig"],
    },
    "applications": {
        "extension": "cogs.applications",
        "slash": [],
        "mention": ["application"],
    },
    "ff": {
        "extension": "cogs.ff_checker",
        "slash": [],
        "mention": ["ffcheck", "ff"],
    },
    "divisions": {
        "extension": "cogs.divisions",
        "slash": [
            "setupdivisions",
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
        "mention": ["giverole", "removerole"],
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


def module_for_mention(keyword):
    keyword = (keyword or "").lower()
    for module, meta in MODULES.items():
        if keyword in {item.lower() for item in meta.get("mention", [])}:
            return module
    return None


def visible_slash_commands(guild_config):
    visible = set(VISIBLE_CORE_COMMANDS)
    for module, meta in MODULES.items():
        if module == CORE_MODULE:
            continue
        if get_module_state(guild_config, module) in {"active", "debug"}:
            visible.update(meta.get("slash", []))
    return {name.lower() for name in visible}


def module_names():
    return sorted(MODULES)
