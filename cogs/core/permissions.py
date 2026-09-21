from __future__ import annotations

from cogs.core.constants import SOLE_OWNER_ID


def is_owner_id(user_id: int | str | None, *_ignored) -> bool:
    if user_id is None:
        return False
    try:
        return int(user_id) == SOLE_OWNER_ID
    except (TypeError, ValueError):
        return False


def guild_enabled(guild_config: dict | None) -> bool:
    if not guild_config:
        return False
    return bool(guild_config.get("enabled", False))


# Interface name used by the security rework plan; kept as an alias so both
# names stay valid for callers.
is_guild_enabled = guild_enabled


def module_enabled(guild_config: dict | None, module_name: str | None) -> bool:
    from cogs.module_registry import CORE_MODULE, get_module_state

    if module_name == CORE_MODULE:
        return True
    if not guild_config or not module_name:
        return False
    return get_module_state(guild_config, module_name) != "disabled"
