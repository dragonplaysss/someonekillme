import pytest

from tests.conftest import FakePermissions, FakeRole


class Channel:
    def __init__(self, channel_id=555):
        self.id = channel_id
        self.sent = []
        self.purged = []

    async def send(self, content=None, **kwargs):
        self.sent.append((content, kwargs))

    async def purge(self, limit=0, **_kwargs):
        self.purged.append(limit)


class Guild:
    id = 123
    name = "Test Guild"

    def __init__(self, bot_member):
        self.me = bot_member

    def get_channel(self, _channel_id):
        return None

    def get_member(self, _member_id):
        return self.me


class Member:
    def __init__(self, user_id, position=1, permissions=None):
        self.id = user_id
        self.top_role = FakeRole(position, user_id, f"role-{user_id}")
        self.guild_permissions = permissions or FakePermissions()
        self.mention = f"<@{user_id}>"
        self.timeouts = []

    async def timeout(self, value, **_kwargs):
        self.timeouts.append(value)


def build_cog(monkeypatch, keyword, *, target=None, target_id=None, args=None, case_id=77):
    import cogs.moderation.moderation_core as moderation_core

    bot_member = Member(10, 10, FakePermissions())
    guild = Guild(bot_member)
    channel = Channel()
    author = Member(20, 20, FakePermissions())
    message = type("Message", (), {"author": author, "guild": guild, "channel": channel})()

    monkeypatch.setattr(
        moderation_core,
        "parse_shorekeeper_trigger",
        lambda _bot, _message: {
            "keyword": keyword,
            "target": target,
            "target_id": target_id,
            "extra": "testing cases",
            "main": "",
            "args": args or [],
        },
    )
    monkeypatch.setattr(
        moderation_core,
        "get_guild_config",
        lambda _guild_id: {"enabled": True, "modules": {"moderation": "active"}},
        raising=False,
    )

    class Allowed:
        allowed = True
        stage = "execute"
        reason = None

    monkeypatch.setattr(moderation_core, "authorize_dangerous_action", lambda _request: Allowed())

    cog = moderation_core.ModerationCore.__new__(moderation_core.ModerationCore)
    cog.bot = type("Bot", (), {"user": type("User", (), {"id": 999})()})()
    cog.is_mod = lambda _member: True
    cog.is_admin = lambda _member: True

    async def block_if_immune(*_args):
        return False

    async def noop(*_args, **_kwargs):
        return None

    async def create_case(*_args, **_kwargs):
        return {"case_id": case_id}

    cog.block_if_immune = block_if_immune
    cog.send_mod_dm = noop
    cog.send_mod_log = noop
    cog.persist_action = noop
    cog.authorize_member_action = lambda _message, **_kwargs: Allowed()
    cog.create_moderation_case = create_case
    cog.deny_authorization = noop

    return moderation_core, cog, message, channel


@pytest.mark.asyncio
async def test_unmute_creates_an_untimeout_case(monkeypatch):
    target = Member(30, 1)
    moderation_core, cog, message, channel = build_cog(
        monkeypatch, "unmute", target=target, target_id=target.id, case_id=42
    )

    await moderation_core.ModerationCore.handle_message(cog, message)

    assert target.timeouts == [None]
    # Check that an embed was sent
    assert len(channel.sent) == 1
    content, kwargs = channel.sent[0]
    # Content should be None, with embed in kwargs
    assert content is None
    assert 'embed' in kwargs
    embed = kwargs['embed']
    # Content should be an embed object
    assert hasattr(embed, 'title')
    assert hasattr(embed, 'description')
    assert hasattr(embed, 'footer')
    # Check embed properties
    assert "Unmute Successful" in embed.title
    assert f"<@{target.id}>" in embed.description  # target.mention
    assert embed.footer.text.startswith("Shorekeeper • Today at")


@pytest.mark.asyncio
async def test_purge_creates_a_case_and_reports_it(monkeypatch):
    moderation_core, cog, message, channel = build_cog(monkeypatch, "purge", args=["25"], case_id=7)

    class Allowed:
        allowed = True
        stage = "execute"
        reason = None

    monkeypatch.setattr(moderation_core, "authorize_dangerous_action", lambda _request: Allowed())

    await moderation_core.ModerationCore.handle_message(cog, message)

    assert channel.purged == [25]
    # Check that an embed was sent
    assert len(channel.sent) == 1
    content, kwargs = channel.sent[0]
    # Content should be None, with embed in kwargs
    assert content is None
    assert 'embed' in kwargs
    embed = kwargs['embed']
    # Content should be an embed object
    assert hasattr(embed, 'title')
    assert hasattr(embed, 'description')
    assert hasattr(embed, 'footer')
    # Check embed properties
    assert "Purge Successful" in embed.title
    assert "Deleted 25 messages" in embed.description
    assert embed.footer.text.startswith("Shorekeeper • Today at")


@pytest.mark.asyncio
async def test_purge_skips_discord_api_when_authorization_fails(monkeypatch):
    moderation_core, cog, message, channel = build_cog(monkeypatch, "purge", args=["25"])

    class Denied:
        allowed = False
        stage = "bot_permission"
        reason = "Shorekeeper needs `manage_messages` for this action."

    monkeypatch.setattr(moderation_core, "authorize_dangerous_action", lambda _request: Denied())
    denied = []

    async def deny_authorization(_message, decision):
        denied.append(decision)

    cog.deny_authorization = deny_authorization

    await moderation_core.ModerationCore.handle_message(cog, message)

    assert channel.purged == []
    assert denied and denied[0].stage == "bot_permission"