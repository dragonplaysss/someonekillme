import pytest

from tests.conftest import FakePermissions, FakeRole


class Member:
    def __init__(self, user_id, role_position, *, permissions=None):
        self.id = user_id
        self.bot = False
        self.top_role = FakeRole(role_position, user_id, f"role-{user_id}")
        self.guild_permissions = permissions or FakePermissions()
        self.mention = f"<@{user_id}>"
        self.roles = []
        self.guild = None
        self.added_roles = []

    async def add_roles(self, role, **_kwargs):
        self.added_roles.append(role)

    async def remove_roles(self, role, **_kwargs):
        pass


class Channel:
    def __init__(self):
        self.sent = []

    async def send(self, content=None, **kwargs):
        self.sent.append((content, kwargs))


class Guild:
    id = 123
    owner_id = 999

    def __init__(self, bot_member, role):
        self.me = bot_member
        self.roles = [role]
        self.owner = None

    def get_role(self, role_id):
        return next((role for role in self.roles if role.id == role_id), None)

    def get_channel(self, _channel_id):
        return None


@pytest.mark.asyncio
async def test_giverole_blocks_equal_bot_hierarchy_target_before_api(monkeypatch):
    import cogs.moderation.role_tools as role_tools

    role = FakeRole(1, 777, "Trusted")
    bot_member = Member(10, 10, permissions=FakePermissions(manage_roles=True))
    guild = Guild(bot_member, role)
    actor = Member(20, 20, permissions=FakePermissions(manage_roles=True))
    target = Member(30, 10)
    for member in (bot_member, actor, target):
        member.guild = guild

    message = type("Message", (), {"author": actor, "guild": guild, "channel": Channel()})()
    monkeypatch.setattr(
        role_tools,
        "parse_shorekeeper_trigger",
        lambda _bot, _message: {
            "keyword": "giverole",
            "target": target,
            "extra": "Trusted | testing hierarchy",
        },
    )
    monkeypatch.setattr(role_tools, "is_mod", lambda _member: True)
    monkeypatch.setattr(role_tools, "immunity_reason", lambda *_args: None)
    monkeypatch.setattr(
        role_tools,
        "get_guild_config",
        lambda _guild_id: {"enabled": True, "modules": {"moderation": "active"}},
        raising=False,
    )

    cog = role_tools.RoleToolsCog(object())

    await cog.on_message(message)

    assert target.added_roles == []
    assert any("highest role" in (content or "").lower() for content, _kwargs in message.channel.sent)
