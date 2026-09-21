from tests.conftest import FakePermissions, FakeRole


class Member:
    def __init__(self, role=None, permissions=None, guild=None):
        self.top_role = role or FakeRole(1, 1, "member")
        self.guild_permissions = permissions or FakePermissions()
        self.guild = guild


def test_only_hardcoded_owner_is_global_owner():
    from cogs.core.permissions import is_owner_id

    assert is_owner_id(708390973712891976) is True
    assert is_owner_id(1) is False


def test_legacy_config_owner_ids_do_not_grant_owner_authority():
    from cogs.core.permissions import is_owner_id

    legacy_config = {"owner_ids": [1, 2, 3]}

    assert legacy_config["owner_ids"]
    assert is_owner_id(1) is False


def test_disabled_guild_blocks_dangerous_action():
    from cogs.core.authz import DangerousActionRequest, authorize_dangerous_action

    request = DangerousActionRequest(
        guild_config={"enabled": False, "modules": {"moderation": "active"}},
        module="moderation",
        actor=None,
        bot_member=None,
        target_member=None,
        target_role=None,
        actor_authorized=True,
        required_bot_permissions=(),
        required_actor_permissions=(),
        security_policy_allowed=True,
        security_action="ban",
    )

    decision = authorize_dangerous_action(request)

    assert decision.allowed is False
    assert decision.stage == "guild_activation"


def test_authorization_blocks_equal_bot_hierarchy_before_execution():
    from cogs.core.authz import DangerousActionRequest, authorize_dangerous_action

    bot = Member(FakeRole(10, 1, "bot"), FakePermissions(ban_members=True))
    target = Member(FakeRole(10, 2, "target"))
    actor = Member(FakeRole(20, 3, "actor"), FakePermissions(ban_members=True))

    decision = authorize_dangerous_action(
        DangerousActionRequest(
            guild_config={"enabled": True, "modules": {"moderation": "active"}},
            module="moderation",
            actor=actor,
            bot_member=bot,
            target_member=target,
            target_role=None,
            actor_authorized=True,
            required_bot_permissions=("ban_members",),
            required_actor_permissions=("ban_members",),
            security_policy_allowed=True,
            security_action="ban",
        )
    )

    assert decision.allowed is False
    assert decision.stage == "bot_hierarchy"
