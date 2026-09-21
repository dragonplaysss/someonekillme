import pytest

from tests.conftest import FakePermissions, FakeRole


class Member:
    def __init__(self, role=None, permissions=None, guild=None, user_id=1):
        self.id = user_id
        self.top_role = role or FakeRole(1, 1, "member")
        self.guild_permissions = permissions or FakePermissions()
        self.guild = guild


def test_discord_roles_cannot_grant_global_ownership():
    from cogs.core.permissions import is_owner_id

    actor = Member(FakeRole(99, 1, "owner-role"), FakePermissions(administrator=True), user_id=111)
    assert is_owner_id(actor.id) is False
    assert is_owner_id(708390973712891976) is True


def test_disabled_module_blocks_dangerous_action():
    from cogs.core.authz import DangerousActionRequest, authorize_dangerous_action

    decision = authorize_dangerous_action(
        DangerousActionRequest(
            guild_config={"enabled": True, "modules": {"moderation": "disabled"}},
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
    )
    assert decision.allowed is False
    assert decision.stage == "module_enabled"


def test_enabled_guild_permits_authorized_action():
    from cogs.core.authz import DangerousActionRequest, authorize_dangerous_action

    bot = Member(FakeRole(10, 1, "bot"), FakePermissions(ban_members=True))
    target = Member(FakeRole(1, 2, "target"))
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
    assert decision.allowed is True
    assert decision.stage == "execute"
def test_registry_registers_owner_activation_commands():
    from cogs.module_registry import MODULES, module_for_mention

    core_mention = {name.lower() for name in MODULES["core"]["mention"]}

    assert {"guild", "activateguild", "deactivateguild", "guildstatus"}.issubset(core_mention)
    assert module_for_mention("activateguild") == "core"
    assert module_for_mention("deactivateguild") == "core"
    assert module_for_mention("guildstatus") == "core"


@pytest.mark.asyncio
async def test_activation_aliases_map_to_owner_only_actions():
    import cogs.module_manager as module_manager

    cog = module_manager.ModuleManager.__new__(module_manager.ModuleManager)
    captured = {}

    async def fake_guild_command(message, trigger):
        captured["message"] = message
        captured["args"] = trigger["args"]
        return "handled"

    cog._guild_command = fake_guild_command

    for keyword, expected_action in (
        ("activateguild", "enable"),
        ("deactivateguild", "disable"),
        ("guildstatus", "status"),
    ):
        captured.clear()
        result = await cog._guild_alias_command(object(), keyword)
        assert result == "handled"
        assert captured["args"] == [expected_action]


async def test_activation_alias_is_denied_for_non_owner():
    import cogs.module_manager as module_manager

    cog = module_manager.ModuleManager.__new__(module_manager.ModuleManager)

    class Guild:
        id = 123

    class Author:
        id = 111

    class Channel:
        def __init__(self):
            self.sent = []

        async def send(self, *args, **kwargs):
            self.sent.append((args, kwargs))

    class Message:
        guild = Guild()
        author = Author()
        channel = Channel()

    message = Message()
    await cog._guild_command(message, {"args": ["enable"], "extra": ""})

    assert message.channel.sent
    embed = message.channel.sent[0][1].get("embed")
    assert embed is not None
    assert "sole" in embed.description.lower() or "owner" in embed.description.lower()


def test_configured_missing_modules_are_reported_separately_from_loaded(monkeypatch):
    import cogs.module_manager as module_manager

    cog = module_manager.ModuleManager.__new__(module_manager.ModuleManager)

    class Bot:
        extensions = {
            extension: object()
            for extension in module_manager.MODULES["moderation"]["extensions"]
        }

    cog.bot = Bot()
    monkeypatch.setattr(module_manager, "get_guild_config", lambda _guild_id: {"modules": {}})

    class Guild:
        id = 123

    lines = cog._module_lines(Guild())

    assert any("moderation" in line and "ACTIVE" in line for line in lines)
    assert any("configured_missing" in line for line in lines)
    assert not any("moderation" in line and "configured_missing" in line for line in lines)
