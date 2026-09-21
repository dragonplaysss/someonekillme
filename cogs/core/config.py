from copy import deepcopy
from pathlib import Path

from cogs.core.persistence import JsonStore


DEFAULT_GUILD = {
    "enabled": False,
    "admin_ids": [],
    "admin_roles": [],
    "mod_roles": [],
    "verify_staff_roles": [],
    "verified_roles": [],
    "ticket_ping_roles": [],
    "welcome_gif_url": None,
    "goodbye_gif_url": None,
    "unverified_role": None,
    "skip_role": None,
    "sealed_role": None,
    "immunity_role": None,
    "snipe_role": None,
    "snipe_cooldown_seconds": 20,
    "channels": {
        "blacklist": None,
        "logging": None,
        "track": None,
        "welcome": None,
        "goodbye": None,
        "tickets": None,
        "mod_logs": None,
        "dashboard": None,
    },
    "modules": {},
    "anti_nuke": {
        "enabled": False,
        "mode": "monitor",
        "bot_add_punishment": "kick",
        "trigger_lockdown_on_bot_add": False,
        "trigger_lockdown_on_mass_action": False,
        "window_seconds": 20,
        "cooldown_seconds": 60,
        "trusted_user_ids": [],
        "trusted_role_ids": [],
        "trusted_bot_ids": [],
        "thresholds": {
            "ban": 5,
            "kick": 5,
            "channel_delete": 3,
            "channel_create": 5,
            "role_delete": 3,
            "role_create": 5,
            "webhook": 4,
            "guild_update": 3,
            "role_update": 3,
            "raid_join": 8,
        },
    },
    "lockdown": {
        "enabled": False,
        "activated_by": None,
        "activated_at": None,
        "channel_ids": [],
        "saved_overwrites": {},
    },
}


def default_config() -> dict:
    return {
        "guilds": {},
        "roblox_auth": {"authorized_guild_ids": []},
    }


class ConfigService:
    def __init__(self, path: str | Path):
        self.store = JsonStore(path, default_config)

    async def get_config(self) -> dict:
        return await self.store.read()

    async def get_guild_config(self, guild_id: int) -> dict:
        gid = str(guild_id)

        async def ensure(data):
            guilds = data.setdefault("guilds", {})
            cfg = guilds.setdefault(gid, deepcopy(DEFAULT_GUILD))
            merge_guild_defaults(cfg)

        data = await self.store.update(ensure)
        return data["guilds"][gid]


def merge_guild_defaults(cfg: dict) -> None:
    for key, value in DEFAULT_GUILD.items():
        if key not in cfg:
            cfg[key] = deepcopy(value)
    for nested in ("channels", "modules", "anti_nuke", "lockdown"):
        if not isinstance(cfg.get(nested), dict):
            cfg[nested] = deepcopy(DEFAULT_GUILD[nested])
            continue
        for key, value in DEFAULT_GUILD[nested].items():
            cfg[nested].setdefault(key, deepcopy(value))
