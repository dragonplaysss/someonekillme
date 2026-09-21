import pytest


def build_cog(monkeypatch):
    import cogs.anti_nuke as anti_nuke_module

    cog = anti_nuke_module.AntiNuke.__new__(anti_nuke_module.AntiNuke)
    cog.bot = type("Bot", (), {"user": type("User", (), {"id": 10})()})()
    cog.rate_tracker = anti_nuke_module.RateTracker()

    config = {
        "enabled": True,
        "modules": {"anti_nuke": "active"},
        "anti_nuke": {
            "enabled": True,
            "mode": "enforcement",
            "thresholds": {"raid_join": 2},
            "window_seconds": 20,
            "cooldown_seconds": 60,
            "trigger_lockdown_on_mass_action": False,
        },
    }
    cog._config = lambda _guild: config

    alerts = []
    logs = []

    async def send_alert(guild, title, description):
        alerts.append((title, description))

    async def log(guild, payload):
        logs.append(payload)

    async def forbidden(*_args, **_kwargs):
        raise AssertionError("raid monitoring must never punish a member")

    cog._send_alert = send_alert
    cog._log = log
    cog._punish_actor = forbidden
    cog._remove_added_bot = forbidden
    return cog, alerts, logs


class Guild:
    id = 123
    me = None

    def get_member(self, _member_id):
        return None


class Member:
    def __init__(self, member_id):
        self.id = member_id
        self.bot = False
        self.guild = Guild()
        self.mention = f"<@{member_id}>"


@pytest.mark.asyncio
async def test_raid_join_threshold_alerts_without_punishing(monkeypatch):
    import cogs.anti_nuke as anti_nuke_module

    cog, alerts, logs = build_cog(monkeypatch)
    member = Member(5)

    await anti_nuke_module.AntiNuke.on_member_join(cog, member)
    assert alerts == []
    assert logs == []

    await anti_nuke_module.AntiNuke.on_member_join(cog, member)

    assert logs and logs[0]["action"] == "raid_join"
    assert logs[0]["count"] == 2
    assert alerts and alerts[0][0] == "Anti-Nuke Raid Watch"
    assert "No member was punished" in alerts[0][1]
    assert member.guild.me is None


@pytest.mark.asyncio
async def test_raid_join_monitoring_requires_an_enabled_policy(monkeypatch):
    import cogs.anti_nuke as anti_nuke_module

    cog, alerts, logs = build_cog(monkeypatch)
    cog._config = lambda _guild: {"enabled": True, "modules": {"anti_nuke": "active"}, "anti_nuke": {"enabled": False}}
    member = Member(6)

    await anti_nuke_module.AntiNuke.on_member_join(cog, member)
    await anti_nuke_module.AntiNuke.on_member_join(cog, member)

    assert alerts == []
    assert logs == []


@pytest.mark.asyncio
async def test_bot_additions_are_handled_by_the_bot_path(monkeypatch):
    import cogs.anti_nuke as anti_nuke_module

    cog, _alerts, _logs = build_cog(monkeypatch)
    handled = []

    async def fake_bot_join(member):
        handled.append(member.id)

    cog._handle_bot_join = fake_bot_join
    member = Member(7)
    member.bot = True

    await anti_nuke_module.AntiNuke.on_member_join(cog, member)

    assert handled == [7]