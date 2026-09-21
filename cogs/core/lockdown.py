from __future__ import annotations

from datetime import datetime, timezone


def lockdown_state(guild_config: dict | None) -> dict:
    state = dict((guild_config or {}).get("lockdown") or {})
    state.setdefault("enabled", False)
    state.setdefault("activated_by", None)
    state.setdefault("activated_at", None)
    state.setdefault("channel_ids", [])
    state.setdefault("saved_overwrites", {})
    return state


def is_lockdown_active(guild_config: dict | None) -> bool:
    return bool(lockdown_state(guild_config).get("enabled"))


def activate_lockdown(guild_config: dict, actor_id: int, *, channel_ids=None) -> dict:
    lockdown = guild_config.setdefault("lockdown", {})
    lockdown["enabled"] = True
    lockdown["activated_by"] = int(actor_id)
    lockdown["activated_at"] = datetime.now(timezone.utc).isoformat()
    if channel_ids is not None:
        lockdown["channel_ids"] = [int(channel_id) for channel_id in channel_ids]
    lockdown.setdefault("saved_overwrites", {})
    return lockdown


def deactivate_lockdown(guild_config: dict) -> dict:
    lockdown = guild_config.setdefault("lockdown", {})
    lockdown["enabled"] = False
    lockdown.setdefault("saved_overwrites", {})
    return lockdown
