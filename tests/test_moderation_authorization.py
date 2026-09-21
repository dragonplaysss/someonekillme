import pytest

from tests.conftest import FakePermissions, FakeRole


class Member:
    def __init__(self, user_id, role_position, *, permissions=None):
        self.id = user_id
        self.top_role = FakeRole(role_position, user_id, f"role-{user_id}")
        self.guild_permissions = permissions or FakePermissions()
        self.mention = f"<@{user_id}>"
        self.roles = []
        self.kicked = False
        self.guild = None

    async def kick(self, **_kwargs):
        self.kicked = True

    async def send(self, **_kwargs):
        pass


class Channel:
    def __init__(self):
        self.sent = []

    async def send(self, content=None, **kwargs):
        self.sent.append((content, kwargs))


class Guild:
    id = 123
    name = "Test Guild"
    owner_id = 999

    def __init__(self, bot_member):
        self.me = bot_member

    def get_channel(self, _channel_id):
        return None


def _rendered_text(channel):
    """Collect the text of everything sent to a channel, including embeds."""
    rendered = []
    for content, kwargs in channel.sent:
        if content:
            rendered.append(str(content))
        embed = kwargs.get("embed")
        if embed is not None:
            rendered.append(str(getattr(embed, "title", "") or ""))
            rendered.append(str(getattr(embed, "description", "") or ""))
            for field in getattr(embed, "fields", []):
                rendered.append(str(getattr(field, "value", "") or ""))
    return rendered


@pytest.mark.asyncio
async def test_kick_blocks_equal_bot_hierarchy_before_discord_api(monkeypatch):
    import cogs.moderation.moderation_core as moderation_core

    bot_member = Member(10, 10, permissions=FakePermissions(kick_members=True))
    guild = Guild(bot_member)
    actor = Member(20, 20, permissions=FakePermissions(kick_members=True))
    target = Member(30, 10)
    for member in (bot_member, actor, target):
        member.guild = guild

    channel = Channel()
    message = type("Message", (), {"author": actor, "guild": guild, "channel": channel})()

    monkeypatch.setattr(
        moderation_core,
        "parse_shorekeeper_trigger",
        lambda _bot, _message: {
            "keyword": "kick",
            "target": target,
            "target_id": target.id,
            "extra": "testing hierarchy",
            "main": "",
            "args": [],
        },
    )
    monkeypatch.setattr(
        moderation_core,
        "get_guild_config",
        lambda _guild_id: {"enabled": True, "modules": {"moderation": "active"}},
        raising=False,
    )

    cog = moderation_core.ModerationCore.__new__(moderation_core.ModerationCore)
    cog.bot = object()
    cog.is_mod = lambda _member: True
    cog.is_admin = lambda _member: True

    async def block_if_immune(*_args):
        return False

    async def noop(*_args):
        return None

    cog.block_if_immune = block_if_immune
    cog.send_mod_dm = noop
    cog.send_mod_log = noop
    cog.persist_action = noop

    await moderation_core.ModerationCore.handle_message(cog, message)

    assert target.kicked is False
    rendered = _rendered_text(channel)
    assert any("highest role" in text.lower() for text in rendered)
    assert any("hierarchy protected" in text.lower() for text in rendered)
