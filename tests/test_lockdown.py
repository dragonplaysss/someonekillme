from cogs.core.anti_nuke import RateTracker, evaluate_mass_action, permission_became_dangerous
from tests.conftest import FakePermissions


def test_rate_tracker_requires_threshold_and_respects_cooldown():
    tracker = RateTracker()
    config = {
        "enabled": True,
        "mode": "enforcement",
        "window_seconds": 20,
        "cooldown_seconds": 60,
        "thresholds": {"ban": 3},
        "trigger_lockdown_on_mass_action": True,
    }
    first = evaluate_mass_action(config, tracker, 1, "ban")
    second = evaluate_mass_action(config, tracker, 1, "ban")
    third = evaluate_mass_action(config, tracker, 1, "ban")
    fourth = evaluate_mass_action(config, tracker, 1, "ban")

    assert first.triggered is False
    assert third.triggered is True
    assert third.trigger_lockdown is True
    assert fourth.reason == "cooldown"


def test_monitor_mode_does_not_request_lockdown():
    tracker = RateTracker()
    config = {"enabled": True, "mode": "monitor", "thresholds": {"kick": 1}}
    decision = evaluate_mass_action(config, tracker, 1, "kick")
    assert decision.triggered is True
    assert decision.trigger_lockdown is False
    assert decision.reason == "monitor_only"


def test_authorized_admin_is_not_punished_for_bot_add():
    from cogs.core.anti_nuke import evaluate_bot_addition
    from tests.conftest import FakeRole

    class Member:
        def __init__(self, user_id, position, *, bot=False, roles=None):
            self.id = user_id
            self.bot = bot
            self.top_role = FakeRole(position, user_id)
            self.guild_permissions = FakePermissions(kick_members=True)
            self.roles = roles or []
            self.guild = type("Guild", (), {"owner_id": 0})()

    added_bot = Member(10, 1, bot=True)
    actor = Member(20, 2)
    shorekeeper = Member(30, 10, bot=True)
    decision = evaluate_bot_addition(
        added_bot,
        actor,
        shorekeeper,
        {"admin_ids": [20], "anti_nuke": {"enabled": True, "mode": "enforcement", "bot_add_punishment": "kick"}},
    )
    assert decision.punish_actor is False
    assert decision.reason == "allowlisted_actor"


def test_dangerous_permission_detection():
    before = FakePermissions()
    after = FakePermissions(administrator=True)
    assert permission_became_dangerous(before, after) is True
    assert permission_became_dangerous(after, after) is False
