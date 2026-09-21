import pytest

from tests.conftest import FakePermissions, FakeRole, Role


class Member:
    def __init__(self, user_id, position, *, permissions=None, roles=None):
        self.id = user_id
        self.top_role = FakeRole(position, user_id, f"rank-{user_id}")
        self.guild_permissions = permissions or FakePermissions()
        self.roles = roles or []
        self.mention = f"<@{user_id}>"
        self.added = []
        self.removed = []

    async def add_roles(self, *roles, **_kwargs):
        self.added.extend(roles)

    async def remove_roles(self, *roles, **_kwargs):
        self.removed.extend(roles)


class Channel:
    def __init__(self):
        self.sent = []

    async def send(self, content=None, **kwargs):
        self.sent.append((content, kwargs))


class Guild:
    id = 123

    def __init__(self, bot_member, roles, *, owner_id=123):
        self.me = bot_member
        self.owner_id = owner_id
        self._roles = {role.id: role for role in roles}

    def get_member(self, _member_id):
        return None

    def get_role(self, role_id):
        return self._roles.get(role_id)

    def get_channel(self, _channel_id):
        return None


def rendered(channel):
    texts = []
    for content, kwargs in channel.sent:
        if content:
            texts.append(str(content))
        embed = kwargs.get("embed")
        if embed is not None:
            texts.append(str(getattr(embed, "title", "") or ""))
            texts.append(str(getattr(embed, "description", "") or ""))
    return texts


def build_message(actor, guild, channel):
    return type("Message", (), {"author": actor, "guild": guild, "channel": channel})()


@pytest.mark.asyncio
async def test_legacy_giverole_refuses_roles_above_the_bot(monkeypatch):
    import cogs.roles as roles_module

    too_high_role = Role(50, 900000000000000000, "shield")
    bot_member = Member(10, 10, permissions=FakePermissions(manage_roles=True))
    actor = Member(20, 60, permissions=FakePermissions(manage_roles=True))
    target = Member(30, 1)
    guild = Guild(bot_member, [too_high_role])
    channel = Channel()
    message = build_message(actor, guild, channel)

    monkeypatch.setattr(
        roles_module,
        "parse_shorekeeper_trigger",
        lambda _bot, _message: {
            "keyword": "giverole",
            "target": target,
            "main": f"giverole <@{target.id}> {too_high_role.id}",
            "extra": "",
            "args": [f"{too_high_role.id}"],
        },
    )
    monkeypatch.setattr(
        roles_module,
        "get_guild_config",
        lambda _guild_id: {"enabled": True, "modules": {"moderation": "active"}},
    )
    monkeypatch.setattr(roles_module, "is_admin", lambda _member: True)
    monkeypatch.setattr(roles_module, "immunity_reason", lambda _target, _action: None)

    cog = roles_module.Roles.__new__(roles_module.Roles)
    cog.bot = type("Bot", (), {"get_cog": lambda self, _name: None, "user": type("User", (), {"id": 10})()})()

    await roles_module.Roles.on_message(cog, message)

    assert target.added == []
    texts = " ".join(rendered(channel)).lower()
    assert "hierarchy" in texts, f"Expected hierarchy denial; got: {texts!r}"


@pytest.mark.asyncio
async def test_verify_refuses_verified_roles_above_the_bot(monkeypatch):
    import cogs.verify as verify_module

    too_high_role = Role(50, 900000000000000001, "verified")
    bot_member = Member(10, 10, permissions=FakePermissions(manage_roles=True))
    actor = Member(20, 60, permissions=FakePermissions(manage_roles=True))
    target = Member(30, 1)
    guild = Guild(bot_member, [too_high_role])
    channel = Channel()
    message = build_message(actor, guild, channel)

    monkeypatch.setattr(
        verify_module,
        "parse_shorekeeper_trigger",
        lambda _bot, _message: {
            "keyword": "verify",
            "target": target,
            "main": f"verify <@{target.id}>",
            "extra": "",
            "args": [],
        },
    )
    monkeypatch.setattr(
        verify_module,
        "get_guild_config",
        lambda _guild_id: {
            "enabled": True,
            "modules": {"verify": "active"},
            "verify_staff_roles": [],
            "unverified_role": None,
            "verified_roles": [too_high_role.id],
        },
    )
    monkeypatch.setattr(verify_module, "is_admin", lambda _member: True)
    monkeypatch.setattr(verify_module, "immunity_reason", lambda _target, _action: None)

    cog = verify_module.Verify.__new__(verify_module.Verify)
    cog.bot = type("Bot", (), {"user": type("User", (), {"id": 10})()})()

    await verify_module.Verify.on_message(cog, message)

    assert target.added == []
    texts = " ".join(rendered(channel)).lower()
    assert "hierarchy" in texts, f"Expected hierarchy denial; got: {texts!r}"
