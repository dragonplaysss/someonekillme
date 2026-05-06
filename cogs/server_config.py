import json
import os


PANEL_OWNER_ID = 708390973712891976
CONFIG_PATH = "cogs/moderation/data2/server_config.json"

DEFAULT_CONFIG = {
    "guilds": {}
}

DEFAULT_GUILD = {
    "admin_roles": [],
    "mod_roles": [],
    "verify_staff_roles": [],
    "verified_roles": [],
    "unverified_role": None,
    "skip_role": None,
    "sealed_role": None,
    "channels": {
        "blacklist": None,
        "logging": None,
        "music": None,
        "track": None,
    },
    "music": {
        "webhook_url": None,
        "message_id": None,
    },
}


def load_config():
    if not os.path.exists(CONFIG_PATH):
        return DEFAULT_CONFIG.copy()

    try:
        with open(CONFIG_PATH, "r") as f:
            return json.load(f)
    except json.JSONDecodeError:
        print(f"[Config Error] {CONFIG_PATH} is empty or invalid; using defaults.")
        return DEFAULT_CONFIG.copy()


def save_config(config):
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    with open(CONFIG_PATH, "w") as f:
        json.dump(config, f, indent=4)


def get_guild_config(guild_id):
    config = load_config()
    guilds = config.setdefault("guilds", {})
    gid = str(guild_id)
    if gid not in guilds:
        guilds[gid] = json.loads(json.dumps(DEFAULT_GUILD))
        save_config(config)

    guild_config = guilds[gid]
    for key, value in DEFAULT_GUILD.items():
        if key not in guild_config:
            guild_config[key] = json.loads(json.dumps(value))
    save_config(config)
    return guild_config


def update_guild_config(guild_id, updater):
    config = load_config()
    guilds = config.setdefault("guilds", {})
    gid = str(guild_id)
    guild_config = guilds.setdefault(gid, json.loads(json.dumps(DEFAULT_GUILD)))
    for key, value in DEFAULT_GUILD.items():
        if key not in guild_config:
            guild_config[key] = json.loads(json.dumps(value))

    updater(guild_config)
    save_config(config)
    return guild_config


def get_role_ids(guild_id, key):
    return get_guild_config(guild_id).get(key, [])


def get_channel_id(guild_id, key):
    return get_guild_config(guild_id).get("channels", {}).get(key)


def is_panel_owner(user_id):
    return user_id == PANEL_OWNER_ID


def is_admin(member):
    if member.id == PANEL_OWNER_ID or member.guild_permissions.administrator:
        return True
    roles = set(get_role_ids(member.guild.id, "admin_roles"))
    return any(role.id in roles for role in member.roles)


def is_mod(member):
    if is_admin(member):
        return True
    roles = set(get_role_ids(member.guild.id, "mod_roles"))
    return any(role.id in roles for role in member.roles)
