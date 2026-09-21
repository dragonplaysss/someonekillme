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
        self.edits = []

    async def edit(self, **kwargs):
        self.edits.append(kwargs)


class Channel:
    def __init__(self):
        self.sent = []

    async def send(self, content=None, **kwargs):
        self.sent.append((content, kwargs))


class Guild:
    id = 123
    owner_id = 999

    def __init__(self, bot_member):
        self.me = bot_member
        self.owner = None

    def get_channel(self, _channel_id):
        return None


class NickLocks:
    async def update_one(self, *_args, **_kwargs):
        return None


@pytest.mark.asyncio
async def test_locknick_blocks_equal_bot_hierarchy_before_api(monkeypatch):
    import cogs.moderation.nicklock as nicklock

    bot_member = Member(10, 10, permissions=FakePermissions(manage_nicknames=True))
    guild = Guild(bot_member)
    actor = Member(20, 20, permissions=FakePermissions(manage_nicknames=True))
    target = Member(30, 10)
    for member in (bot_member, actor, target):
        member.guild = guild

    message = type("Message", (), {"author": actor, "guild": guild, "channel": Channel()})()
    monkeypatch.setattr(
        nicklock,
        "parse_shorekeeper_trigger",
        lambda _bot, _message: {
            "keyword": "locknick",
            "target": target,
            "extra": "Guarded",
        },
    )
    monkeypatch.setattr(nicklock, "is_admin", lambda _member: True)
    monkeypatch.setattr(nicklock, "immunity_reason", lambda *_args: None)
    monkeypatch.setattr(
        nicklock,
        "get_guild_config",
        lambda _guild_id: {"enabled": True, "modules": {"moderation": "active"}},
        raising=False,
    )

    cog = nicklock.NickLockCog.__new__(nicklock.NickLockCog)
    cog.bot = object()
    cog.nick_locks = NickLocks()

    async def noop(*_args):
        return None

    cog.send_log = noop

    await nicklock.NickLockCog.on_message(cog, message)

    assert target.edits == []
    assert any("highest role" in (content or "").lower() for content, _kwargs in message.channel.sent)