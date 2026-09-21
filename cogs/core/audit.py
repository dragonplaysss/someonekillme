from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import discord


DEFAULT_AUDIT_WINDOW_SECONDS = 120


@dataclass(frozen=True)
class AuditAttribution:
    actor: object | None
    reason: str
    entry: object | None = None


def _utc_now():
    return discord.utils.utcnow()


def audit_entry_matches(
    entry,
    *,
    target_id: int | None,
    now,
    window_seconds: int,
    expected_action=None,
) -> bool:
    if expected_action is not None:
        entry_action = getattr(entry, "action", None)
        if entry_action not in {None, expected_action}:
            return False
    target = getattr(entry, "target", None)
    if target_id is not None and getattr(target, "id", None) != target_id:
        return False
    created_at = getattr(entry, "created_at", None)
    if created_at is None:
        return False
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    age = abs((now - created_at).total_seconds())
    return age <= window_seconds


def classify_audit_matches(matches: list) -> str:
    if len(matches) == 1:
        return "audit_attribution_identified"
    if matches:
        return "audit_attribution_ambiguous"
    return "audit_attribution_missing"


async def find_unique_audit_actor(
    guild,
    action,
    *,
    target_id: int | None = None,
    limit: int = 5,
    window_seconds: int = DEFAULT_AUDIT_WINDOW_SECONDS,
    now=None,
) -> AuditAttribution:
    if action is None:
        return AuditAttribution(None, "audit_not_applicable")
    now = now or _utc_now()
    try:
        matches = []
        async for entry in guild.audit_logs(limit=limit, action=action):
            if audit_entry_matches(
                entry,
                target_id=target_id,
                now=now,
                window_seconds=window_seconds,
                expected_action=action,
            ):
                matches.append(entry)
    except (discord.Forbidden, discord.HTTPException):
        return AuditAttribution(None, "audit_attribution_missing")

    reason = classify_audit_matches(matches)
    if reason != "audit_attribution_identified":
        return AuditAttribution(None, reason)

    actor = getattr(matches[0], "user", None)
    if not actor:
        return AuditAttribution(None, "audit_attribution_missing", matches[0])
    actor_member = guild.get_member(actor.id)
    if not actor_member:
        return AuditAttribution(None, "audit_actor_not_member", matches[0])
    return AuditAttribution(actor_member, "audit_attribution_identified", matches[0])
