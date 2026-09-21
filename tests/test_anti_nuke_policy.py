from tests.conftest import FakePermissions, FakeRole


class Member:
    def __init__(self, user_id, role_position, *, bot=False, permissions=None, roles=None, guild_owner=False):
        self.id = user_id
        self.bot = bot
        self.top_role = FakeRole(role_position, user_id, f"role-{user_id}")
        self.guild_permissions = permissions or FakePermissions()
        self.roles = roles or []
        self.guild = type("Guild", (), {"owner_id": user_id if guild_owner else 0})()


def anti_nuke_config(**overrides):
    config = {
        "enabled": True,
        "mode": "enforcement",
        "bot_add_punishment": "kick",
        "trigger_lockdown_on_bot_add": False,
        "trusted_bot_ids": [],
        "trusted_user_ids": [],
        "trusted_role_ids": [],
    }
    config.update(overrides)
    return {"enabled": True, "anti_nuke": config}


def test_anti_nuke_disabled_by_default_for_bot_additions():
    from cogs.core.anti_nuke import evaluate_bot_addition

    added_bot = Member(10, 1, bot=True)
    actor = Member(20, 1)
    shorekeeper = Member(30, 10, bot=True, permissions=FakePermissions(kick_members=True))

    decision = evaluate_bot_addition(added_bot, actor, shorekeeper, {"enabled": True})

    assert decision.remove_added_bot is False
    assert decision.punish_actor is False
    assert decision.reason == "anti_nuke_disabled"


def test_configured_admin_ids_and_admin_roles_are_trusted_for_bot_adds():
    from cogs.core.anti_nuke import evaluate_bot_addition
    from tests.conftest import FakeRole

    added_bot = Member(10, 1, bot=True)
    admin_by_id = Member(20, 1)
    admin_by_role = Member(21, 1, roles=[FakeRole(1, 77, "admin-role")])
    shorekeeper = Member(30, 10, bot=True, permissions=FakePermissions(kick_members=True))

    by_id = evaluate_bot_addition(
        added_bot,
        admin_by_id,
        shorekeeper,
        {**anti_nuke_config(), "admin_ids": [20]},
    )
    by_role = evaluate_bot_addition(
        added_bot,
        admin_by_role,
        shorekeeper,
        {**anti_nuke_config(), "admin_roles": [77]},
    )

    for decision in (by_id, by_role):
        assert decision.remove_added_bot is False
        assert decision.punish_actor is False
        assert decision.reason == "allowlisted_actor"


def test_configured_admin_trust_does_not_disable_mass_action_detection():
    from cogs.core.anti_nuke import RateTracker, evaluate_mass_action

    actor = Member(20, 1)
    policy = {"enabled": True, "mode": "enforcement", "thresholds": {"ban": 1}}
    decision = evaluate_mass_action(
        policy,
        RateTracker(),
        123,
        "ban",
        actor=actor,
        guild_config={"admin_ids": [20], "anti_nuke": policy},
    )

    assert decision.triggered is True
    assert decision.reason == "threshold_exceeded"


def test_unauthorized_bot_add_without_clear_actor_does_not_punish():
    from cogs.core.anti_nuke import evaluate_bot_addition

    added_bot = Member(10, 1, bot=True)
    shorekeeper = Member(30, 10, bot=True, permissions=FakePermissions(kick_members=True))

    decision = evaluate_bot_addition(added_bot, None, shorekeeper, anti_nuke_config())

    assert decision.remove_added_bot is False
    assert decision.punish_actor is False
    assert decision.should_log is True
    assert decision.reason == "audit_attribution_missing"


def test_allowlisted_bot_addition_is_ignored():
    from cogs.core.anti_nuke import evaluate_bot_addition

    added_bot = Member(10, 1, bot=True)
    actor = Member(20, 1)
    shorekeeper = Member(30, 10, bot=True, permissions=FakePermissions(kick_members=True))

    decision = evaluate_bot_addition(
        added_bot,
        actor,
        shorekeeper,
        anti_nuke_config(trusted_bot_ids=[10]),
    )

    assert decision.remove_added_bot is False
    assert decision.punish_actor is False
    assert decision.reason == "allowlisted_bot"


def test_enforcement_bot_addition_removes_bot_and_punishes_actor_when_safe():
    from cogs.core.anti_nuke import evaluate_bot_addition

    added_bot = Member(10, 1, bot=True)
    actor = Member(20, 2)
    shorekeeper = Member(30, 10, bot=True, permissions=FakePermissions(kick_members=True))

    decision = evaluate_bot_addition(
        added_bot,
        actor,
        shorekeeper,
        anti_nuke_config(trigger_lockdown_on_bot_add=True),
    )

    assert decision.remove_added_bot is True
    assert decision.punish_actor is True
    assert decision.punishment == "kick"
    assert decision.trigger_lockdown is True
    assert decision.reason == "unauthorized_bot_add"


def test_monitor_mode_logs_without_enforcement():
    from cogs.core.anti_nuke import evaluate_bot_addition

    added_bot = Member(10, 1, bot=True)
    actor = Member(20, 2)
    shorekeeper = Member(30, 10, bot=True, permissions=FakePermissions(kick_members=True))

    decision = evaluate_bot_addition(added_bot, actor, shorekeeper, anti_nuke_config(mode="monitor"))

    assert decision.remove_added_bot is False
    assert decision.punish_actor is False
    assert decision.should_log is True
    assert decision.reason == "monitor_only"


def test_bot_hierarchy_blocks_anti_nuke_actions():
    from cogs.core.anti_nuke import evaluate_bot_addition

    added_bot = Member(10, 10, bot=True)
    actor = Member(20, 2)
    shorekeeper = Member(30, 10, bot=True, permissions=FakePermissions(kick_members=True))

    decision = evaluate_bot_addition(added_bot, actor, shorekeeper, anti_nuke_config())

    assert decision.remove_added_bot is False
    assert decision.punish_actor is False
    assert decision.reason == "bot_hierarchy"
