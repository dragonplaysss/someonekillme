from dataclasses import dataclass


@dataclass(frozen=True)
class HierarchyResult:
    allowed: bool
    reason: str | None = None


def _guild(member):
    return getattr(member, "guild", None)


def is_guild_owner(member) -> bool:
    guild = _guild(member)
    if member is None or guild is None:
        return False
    if member == getattr(guild, "owner", None):
        return True
    owner_id = getattr(guild, "owner_id", None)
    return owner_id is not None and getattr(member, "id", None) == owner_id


def can_bot_act_on_member(bot_member, target) -> HierarchyResult:
    if is_guild_owner(target):
        return HierarchyResult(False, "Shorekeeper cannot act on the server owner.")
    if target.top_role >= bot_member.top_role:
        return HierarchyResult(
            False,
            "Shorekeeper cannot act on that member because their highest role is equal to or above Shorekeeper.",
        )
    return HierarchyResult(True)


def can_bot_manage_role(bot_member, role) -> HierarchyResult:
    if role >= bot_member.top_role:
        return HierarchyResult(
            False,
            "Shorekeeper cannot manage that role because it is equal to or above Shorekeeper.",
        )
    return HierarchyResult(True)


def can_actor_act_on_member(actor, target) -> HierarchyResult:
    if is_guild_owner(actor):
        return HierarchyResult(True)
    if is_guild_owner(target):
        return HierarchyResult(False, "You cannot target the server owner.")
    if target.top_role >= actor.top_role:
        return HierarchyResult(
            False,
            "You cannot target a member whose highest role is equal to or above your highest role.",
        )
    return HierarchyResult(True)


def can_actor_manage_role(actor, role) -> HierarchyResult:
    if is_guild_owner(actor):
        return HierarchyResult(True)
    if role >= actor.top_role:
        return HierarchyResult(
            False,
            "You cannot manage a role equal to or above your highest role.",
        )
    return HierarchyResult(True)
