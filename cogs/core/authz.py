from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from cogs.core.hierarchy import (
    can_actor_act_on_member,
    can_actor_manage_role,
    can_bot_act_on_member,
    can_bot_manage_role,
)
from cogs.core.permissions import guild_enabled, module_enabled


@dataclass(frozen=True)
class AuthorizationDecision:
    allowed: bool
    stage: str
    reason: str | None = None


@dataclass(frozen=True)
class DangerousActionRequest:
    guild_config: dict
    module: str
    actor: object | None
    bot_member: object | None
    target_member: object | None
    target_role: object | None
    actor_authorized: bool
    required_bot_permissions: Iterable[str]
    required_actor_permissions: Iterable[str]
    security_policy_allowed: bool
    security_action: str


def _has_permissions(member: object | None, permissions: Iterable[str]) -> bool:
    if member is None:
        return not tuple(permissions)
    guild_permissions = getattr(member, "guild_permissions", None)
    return all(bool(getattr(guild_permissions, permission, False)) for permission in permissions)


def _deny(stage: str, reason: str) -> AuthorizationDecision:
    return AuthorizationDecision(False, stage, reason)


def authorize_dangerous_action(request: DangerousActionRequest) -> AuthorizationDecision:
    if not guild_enabled(request.guild_config):
        return _deny("guild_activation", "This guild has not been activated for Shorekeeper.")

    if not module_enabled(request.guild_config, request.module):
        return _deny("module_enabled", f"The {request.module} module is disabled.")

    if not request.actor_authorized:
        return _deny("actor_authorization", "The actor is not authorized for this action.")

    if not _has_permissions(request.actor, request.required_actor_permissions):
        return _deny("discord_permission", "The actor lacks the required Discord permission.")

    if request.target_member is not None:
        actor_hierarchy = can_actor_act_on_member(request.actor, request.target_member)
        if not actor_hierarchy.allowed:
            return _deny("actor_hierarchy", actor_hierarchy.reason or "Actor hierarchy denied.")

    if request.target_role is not None:
        actor_role_hierarchy = can_actor_manage_role(request.actor, request.target_role)
        if not actor_role_hierarchy.allowed:
            return _deny("actor_hierarchy", actor_role_hierarchy.reason or "Actor role hierarchy denied.")

    if not _has_permissions(request.bot_member, request.required_bot_permissions):
        return _deny("bot_permission", "Shorekeeper lacks the required Discord permission.")

    if request.target_member is not None:
        bot_hierarchy = can_bot_act_on_member(request.bot_member, request.target_member)
        if not bot_hierarchy.allowed:
            return _deny("bot_hierarchy", bot_hierarchy.reason or "Bot hierarchy denied.")

    if request.target_role is not None:
        bot_role_hierarchy = can_bot_manage_role(request.bot_member, request.target_role)
        if not bot_role_hierarchy.allowed:
            return _deny("bot_hierarchy", bot_role_hierarchy.reason or "Bot role hierarchy denied.")

    if not request.security_policy_allowed:
        return _deny("security_policy", "The configured security policy blocked this action.")

    return AuthorizationDecision(True, "execute", None)
