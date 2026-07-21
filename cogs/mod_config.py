import json
import os
import time
from copy import deepcopy
from typing import Any, Callable


CONFIG_PATH = "cogs/moderation/data2/mod_config.json"

DEFAULT_CONFIG = {
    "guilds": {}
}

DEFAULT_GUILD = {
    "account_manager_role": None,
}

_CONFIG_CACHE = None
_CONFIG_MTIME = None


def _default_config():
    return deepcopy(DEFAULT_CONFIG)


def _default_guild():
    return deepcopy(DEFAULT_GUILD)


def _ensure_guild_defaults(guild_config):
    changed = False
    for key, value in DEFAULT_GUILD.items():
        if key not in guild_config:
            guild_config[key] = deepcopy(value)
            changed = True
    return changed


def load_mod_config():
    global _CONFIG_CACHE, _CONFIG_MTIME

    current_mtime = os.path.getmtime(CONFIG_PATH) if os.path.exists(CONFIG_PATH) else None
    if _CONFIG_CACHE is not None and current_mtime == _CONFIG_MTIME:
        return deepcopy(_CONFIG_CACHE)

    if not os.path.exists(CONFIG_PATH):
        config = _default_config()
        save_mod_config(config)
        return config

    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            config = json.load(f)
        if not isinstance(config, dict):
            raise ValueError("Config root must be an object.")
        config.setdefault("guilds", {})
        changed = False
        for guild_config in config["guilds"].values():
            if isinstance(guild_config, dict):
                changed = _ensure_guild_defaults(guild_config) or changed
        _CONFIG_CACHE = deepcopy(config)
        _CONFIG_MTIME = current_mtime
        if changed:
            save_mod_config(config)
        return config
    except (json.JSONDecodeError, ValueError):
        try:
            ts = time.strftime("%Y%m%d-%H%M%S")
            backup_path = f"{CONFIG_PATH}.corrupt.{ts}"
            if os.path.exists(CONFIG_PATH):
                os.replace(CONFIG_PATH, backup_path)
            print(f"[Mod Config Error] {CONFIG_PATH} invalid; backed up to {backup_path}")
        except Exception:
            print(f"[Mod Config Error] {CONFIG_PATH} is empty or invalid; using defaults.")

        config = _default_config()
        save_mod_config(config)
        return config


def save_mod_config(config):
    global _CONFIG_CACHE, _CONFIG_MTIME

    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=4)
    _CONFIG_CACHE = deepcopy(config)
    _CONFIG_MTIME = os.path.getmtime(CONFIG_PATH) if os.path.exists(CONFIG_PATH) else None


def get_mod_guild_config(guild_id: int):
    config = load_mod_config()
    guilds = config.setdefault("guilds", {})
    gid = str(guild_id)
    if gid not in guilds:
        guilds[gid] = _default_guild()
        save_mod_config(config)

    guild_config = guilds[gid]
    if _ensure_guild_defaults(guild_config):
        save_mod_config(config)
    return guild_config


def update_mod_guild_config(guild_id: int, updater: Callable[[dict[str, Any]], None]):
    config = load_mod_config()
    guilds = config.setdefault("guilds", {})
    gid = str(guild_id)
    guild_config = guilds.setdefault(gid, _default_guild())
    _ensure_guild_defaults(guild_config)

    updater(guild_config)
    save_mod_config(config)
    return guild_config
