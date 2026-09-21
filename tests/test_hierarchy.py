from dataclasses import dataclass

from tests.conftest import FakePermissions, FakeRole


@dataclass
class FakeMember:
    id: int
    top_role: FakeRole
    guild_permissions: FakePermissions
    guild: object = None


def test_bot_cannot_act_on_equal_role_member():
    from cogs.core.hierarchy import can_bot_act_on_member

    bot = FakeMember(1, FakeRole(10, 100, "bot"), FakePermissions())
    target = FakeMember(2, FakeRole(10, 200, "target"), FakePermissions())

    result = can_bot_act_on_member(bot, target)

    assert result.allowed is False
    assert "equal to or above Shorekeeper" in result.reason


def test_bot_can_act_on_lower_role_member():
    from cogs.core.hierarchy import can_bot_act_on_member

    bot = FakeMember(1, FakeRole(10, 100, "bot"), FakePermissions())
    target = FakeMember(2, FakeRole(9, 200, "target"), FakePermissions())

    assert can_bot_act_on_member(bot, target).allowed is True


def test_administrator_does_not_bypass_bot_hierarchy():
    from cogs.core.hierarchy import can_bot_act_on_member

    bot = FakeMember(1, FakeRole(10, 100, "bot"), FakePermissions(administrator=True))
    target = FakeMember(2, FakeRole(11, 200, "target"), FakePermissions())

    assert can_bot_act_on_member(bot, target).allowed is False


def test_bot_never_acts_on_guild_owner_by_owner_id():
    from cogs.core.hierarchy import can_bot_act_on_member

    class Guild:
        owner = None
        owner_id = 2

    guild = Guild()
    bot = FakeMember(1, FakeRole(20, 100, "bot"), FakePermissions(), guild=guild)
    target = FakeMember(2, FakeRole(1, 200, "owner"), FakePermissions(), guild=guild)

    result = can_bot_act_on_member(bot, target)

    assert result.allowed is False
    assert "server owner" in result.reason


def test_bot_never_acts_on_guild_owner_object():
    from cogs.core.hierarchy import can_bot_act_on_member

    class Guild:
        owner = None

    guild = Guild()
    bot = FakeMember(1, FakeRole(20, 100, "bot"), FakePermissions(), guild=guild)
    target = FakeMember(2, FakeRole(1, 200, "owner"), FakePermissions(), guild=guild)
    guild.owner = target

    result = can_bot_act_on_member(bot, target)

    assert result.allowed is False
    assert "server owner" in result.reason
