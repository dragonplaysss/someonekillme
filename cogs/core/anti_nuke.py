from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from time import monotonic

from cogs.core.hierarchy import can_bot_act_on_member
from cogs.core.permissions import is_owner_id


DEFAULT_THRESHOLDS = {
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
}

DANGEROUS_GUILD_ATTRS = (
    "owner_id",
    "verification_level",
    "mfa_level",
    "explicit_content_filter",
    "vanity_url_code",
    "widget_enabled",
)

DANGEROUS_PERMISSIONS = (
    "administrator",
    "ban_members",
    "kick_members",
    "manage_guild",
    "manage_roles",
    "manage_channels",
    "manage_webhooks",
    "mention_everyone",
)


@dataclass(frozen=True)
class BotAdditionDecision:
    remove_added_bot: bool
    punish_actor: bool
    punishment: str | None
    trigger_lockdown: bool
    should_log: bool
    reason: str


@dataclass(frozen=True)
class MassActionDecision:
    triggered: bool
    should_log: bool
    trigger_lockdown: bool
    reason: str
    count: int = 0


class RateTracker:
    def __init__(self):
        self._events: dict[tuple[int, str], deque] = defaultdict(deque)
        self._cooldowns: dict[tuple[int, str], float] = {}

    def record(
        self,
        guild_id: int,
        action: str,
        *,
        threshold: int,
        window_seconds: float,
        cooldown_seconds: float,
        now: float | None = None,
    ) -> MassActionDecision:
        now = monotonic() if now is None else now
        key = (int(guild_id), action)
        cooldown_until = self._cooldowns.get(key, 0)
        bucket = self._events[key]
        bucket.append(now)
        while bucket and now - bucket[0] > window_seconds:
            bucket.popleft()
        count = len(bucket)
        if count < threshold:
            return MassActionDecision(False, False, False, "below_threshold", count)
        if now < cooldown_until:
            return MassActionDecision(True, False, False, "cooldown", count)
        self._cooldowns[key] = now + cooldown_seconds
        return MassActionDecision(True, True, False, "threshold_exceeded", count)


def _ids(values) -> set[int]:
    result = set()
    for value in values or []:
        try:
            result.add(int(value))
        except (TypeError, ValueError):
            continue
    return result


def _has_role(member, role_ids: set[int]) -> bool:
    return any(getattr(role, "id", None) in role_ids for role in getattr(member, "roles", []))


def _has_permission(member, permission: str) -> bool:
    permissions = getattr(member, "guild_permissions", None)
    return bool(getattr(permissions, permission, False))


def _decision(
    reason: str,
    *,
    remove_added_bot: bool = False,
    punish_actor: bool = False,
    punishment: str | None = None,
    trigger_lockdown: bool = False,
    should_log: bool = True,
) -> BotAdditionDecision:
    return BotAdditionDecision(remove_added_bot, punish_actor, punishment, trigger_lockdown, should_log, reason)


def actor_is_hardcoded_trusted(actor) -> bool:
    return is_owner_id(getattr(actor, "id", None) if actor is not None else None)


def anti_nuke_allowlist(guild_config: dict | None) -> dict[str, set[int]]:
    policy = (guild_config or {}).get("anti_nuke") or {}
    return {
        "bots": _ids(policy.get("trusted_bot_ids")),
        "users": _ids(policy.get("trusted_user_ids")),
        "roles": _ids(policy.get("trusted_role_ids")),
    }


def actor_is_allowlisted(actor, guild_config: dict | None) -> bool:
    if actor is None:
        return False
    if actor_is_hardcoded_trusted(actor):
        return True
    allow = anti_nuke_allowlist(guild_config)
    if getattr(actor, "id", None) in allow["users"]:
        return True
    return _has_role(actor, allow["roles"])


def actor_is_configured_admin(actor, guild_config: dict | None) -> bool:
    """Configured guild admins are trusted operators.

    Bot additions by these actors are treated as authorized instead of
    unauthorized. Mass-action detection still watches every actor, so a
    compromised admin account is not exempt from rate-based alarms.
    """
    actor_id = getattr(actor, "id", None)
    if actor_id is None:
        return False
    config = guild_config or {}
    if actor_id in _ids(config.get("admin_ids")):
        return True
    return _has_role(actor, _ids(config.get("admin_roles")))


def bot_is_allowlisted(member, guild_config: dict | None) -> bool:
    return getattr(member, "id", None) in anti_nuke_allowlist(guild_config)["bots"]


def mutate_allowlist(policy: dict, kind: str, action: str, entity_id: int) -> list[int]:
    key = {"bot": "trusted_bot_ids", "user": "trusted_user_ids", "role": "trusted_role_ids"}[kind]
    values = [int(item) for item in policy.setdefault(key, []) if str(item).isdigit() or isinstance(item, int)]
    entity_id = int(entity_id)
    if action == "add" and entity_id not in values:
        values.append(entity_id)
    if action == "remove" and entity_id in values:
        values.remove(entity_id)
    policy[key] = values
    return values


def actor_is_explicitly_authorized(actor, guild_config: dict | None) -> bool:
    return actor_is_allowlisted(actor, guild_config)


def evaluate_bot_addition(added_member, actor, bot_member, guild_config: dict | None) -> BotAdditionDecision:
    if not getattr(added_member, "bot", False):
        return _decision("not_a_bot", should_log=False)

    policy = (guild_config or {}).get("anti_nuke") or {}
    if not policy.get("enabled", False):
        return _decision("anti_nuke_disabled", should_log=False)

    trusted_bot_ids = _ids(policy.get("trusted_bot_ids"))
    if getattr(added_member, "id", None) in trusted_bot_ids or bot_is_allowlisted(added_member, guild_config):
        return _decision("allowlisted_bot", should_log=False)

    if actor is None:
        return _decision("audit_attribution_missing")

    if actor_is_allowlisted(actor, guild_config) or actor_is_configured_admin(actor, guild_config):
        # Explicit anti-nuke allowlist entries and configured guild admins both
        # count as trusted operators for their own bot additions.
        return _decision("allowlisted_actor", should_log=False)

    if policy.get("mode", "monitor") != "enforcement":
        return _decision("monitor_only")

    if not _has_permission(bot_member, "kick_members"):
        return _decision("bot_permission")

    added_bot_hierarchy = can_bot_act_on_member(bot_member, added_member)
    if not added_bot_hierarchy.allowed:
        return _decision("bot_hierarchy")

    punishment = policy.get("bot_add_punishment") or "kick"
    punish_actor = punishment != "none"
    if punish_actor and actor_is_explicitly_authorized(actor, guild_config):
        punish_actor = False
    if punishment == "ban" and not _has_permission(bot_member, "ban_members"):
        return _decision("bot_permission")
    if punishment == "kick" and not _has_permission(bot_member, "kick_members"):
        return _decision("bot_permission")
    if punish_actor:
        actor_hierarchy = can_bot_act_on_member(bot_member, actor)
        if not actor_hierarchy.allowed:
            return _decision("bot_hierarchy")

    return _decision(
        "unauthorized_bot_add",
        remove_added_bot=True,
        punish_actor=punish_actor,
        punishment=punishment,
        trigger_lockdown=bool(policy.get("trigger_lockdown_on_bot_add", False)),
    )


def evaluate_mass_action(
    policy: dict | None,
    tracker: RateTracker,
    guild_id: int,
    action: str,
    *,
    actor=None,
    guild_config: dict | None = None,
) -> MassActionDecision:
    policy = policy or {}
    if not policy.get("enabled", False):
        return MassActionDecision(False, False, False, "anti_nuke_disabled")
    config = guild_config if guild_config is not None else {"anti_nuke": policy}
    if actor is not None and actor_is_allowlisted(actor, config):
        return MassActionDecision(False, False, False, "allowlisted_actor")
    thresholds = dict(DEFAULT_THRESHOLDS)
    thresholds.update(policy.get("thresholds") or {})
    decision = tracker.record(
        guild_id,
        action,
        threshold=int(thresholds.get(action, 5)),
        window_seconds=float(policy.get("window_seconds", 20)),
        cooldown_seconds=float(policy.get("cooldown_seconds", 60)),
    )
    if not decision.triggered:
        return decision
    if decision.reason == "cooldown":
        return decision
    if policy.get("mode", "monitor") != "enforcement":
        return MassActionDecision(True, True, False, "monitor_only", decision.count)
    trigger_lockdown = bool(policy.get("trigger_lockdown_on_mass_action", False))
    return MassActionDecision(True, True, trigger_lockdown, "threshold_exceeded", decision.count)


def permission_became_dangerous(before_permissions, after_permissions) -> bool:
    for name in DANGEROUS_PERMISSIONS:
        before = bool(getattr(before_permissions, name, False))
        after = bool(getattr(after_permissions, name, False))
        if after and not before:
            return True
    return False


def guild_update_is_dangerous(before, after) -> bool:
    for attr in DANGEROUS_GUILD_ATTRS:
        if getattr(before, attr, None) != getattr(after, attr, None):
            return True
    return False


def actor_is_self(actor, bot_member) -> bool:
    if actor is None or bot_member is None:
        return False
    return getattr(actor, "id", None) == getattr(bot_member, "id", None)


def anti_nuke_status_label(policy: dict | None) -> str:
    policy = policy or {}
    if not policy.get("enabled", False):
        return "DISABLED"
    mode = str(policy.get("mode") or "monitor").strip().lower()
    if mode == "enforcement":
        return "ENFORCEMENT"
    return "MONITOR"


def format_anti_nuke_status(guild_config: dict | None) -> str:
    policy = (guild_config or {}).get("anti_nuke") or {}
    allow = anti_nuke_allowlist(guild_config)
    thresholds = dict(DEFAULT_THRESHOLDS)
    thresholds.update(policy.get("thresholds") or {})
    threshold_text = ", ".join(f"{key}={value}" for key, value in sorted(thresholds.items()))
    lockdown = (guild_config or {}).get("lockdown") or {}
    return (
        f"Status: **{anti_nuke_status_label(policy)}**\n"
        f"Enabled: `{bool(policy.get('enabled', False))}`\n"
        f"Mode: `{policy.get('mode', 'monitor')}`\n"
        f"Window: `{policy.get('window_seconds', 20)}s`\n"
        f"Cooldown: `{policy.get('cooldown_seconds', 60)}s`\n"
        f"Bot-add punishment: `{policy.get('bot_add_punishment', 'kick')}`\n"
        f"Lockdown on unauthorized bot: `{bool(policy.get('trigger_lockdown_on_bot_add', False))}`\n"
        f"Lockdown on mass action: `{bool(policy.get('trigger_lockdown_on_mass_action', False))}`\n"
        f"Emergency lockdown active: `{bool(lockdown.get('enabled', False))}`\n"
        f"Trusted bots: `{len(allow['bots'])}`\n"
        f"Trusted users: `{len(allow['users'])}`\n"
        f"Trusted roles: `{len(allow['roles'])}`\n"
        f"Thresholds: `{threshold_text}`"
    )


def format_allowlist(guild_config: dict | None) -> str:
    allow = anti_nuke_allowlist(guild_config)
    def ids(values):
        return ", ".join(f"`{item}`" for item in sorted(values)) or "none"
    return (
        "Hard-coded Shorekeeper trust: sole owner `708390973712891976`\n"
        f"Allowlisted bots: {ids(allow['bots'])}\n"
        f"Allowlisted users: {ids(allow['users'])}\n"
        f"Allowlisted roles: {ids(allow['roles'])}"
    )
