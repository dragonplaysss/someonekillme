import json
import os
import time


PANEL_OWNER_ID = 708390973712891976
CONFIG_PATH = "cogs/moderation/data2/server_config.json"

DEFAULT_CONFIG = {
    "guilds": {}
}

DEFAULT_GUILD = {
    "owner_ids": [PANEL_OWNER_ID],
    "admin_roles": [],
    "mod_roles": [],
    "verify_staff_roles": [],
    "verified_roles": [],
    "ticket_ping_roles": [],
    "unverified_role": None,
    "skip_role": None,
    "sealed_role": None,
    "channels": {
        "blacklist": None,
        "logging": None,
        "track": None,
        "welcome": None,
        "goodbye": None,
        "tickets": None,
        "mod_logs": None,
    },
}


def load_config():
    if not os.path.exists(CONFIG_PATH):
        config = json.loads(json.dumps(DEFAULT_CONFIG))
        save_config(config)
        return config

    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            config = json.load(f)
        if not isinstance(config, dict):
            raise ValueError("Config root must be an object.")
        config.setdefault("guilds", {})
        return config
    except (json.JSONDecodeError, ValueError):
        # If config is corrupted/invalid, back it up so it can be recovered.
        try:
            ts = time.strftime("%Y%m%d-%H%M%S")
            backup_path = f"{CONFIG_PATH}.corrupt.{ts}"
            if os.path.exists(CONFIG_PATH):
                os.replace(CONFIG_PATH, backup_path)
            print(f"[Config Error] {CONFIG_PATH} invalid; backed up to {backup_path}")
        except Exception:
            print(f"[Config Error] {CONFIG_PATH} is empty or invalid; using defaults.")

        config = json.loads(json.dumps(DEFAULT_CONFIG))
        save_config(config)
        return config


def save_config(config):
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
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


def is_owner_id(guild_id, user_id):
    owner_ids = set(get_guild_config(guild_id).get("owner_ids", []))
    owner_ids.add(PANEL_OWNER_ID)
    return user_id in owner_ids
