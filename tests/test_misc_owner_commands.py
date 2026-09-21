import pytest


class Channel:
    def __init__(self):
        self.sent = []

    async def send(self, content=None, **kwargs):
        self.sent.append((content, kwargs))


class EmptyCollection:
    async def find_one(self, *_args, **_kwargs):
        return None


@pytest.mark.asyncio
async def test_setowner_command_is_disabled(monkeypatch):
    import cogs.misc_tools as misc_tools

    # Use a non-owner ID to test that the command is disabled for non-owners
    message = type(
        "Message",
        (),
        {
            "author": type("Author", (), {"id": 12345, "bot": False})(),  # Non-owner ID
            "guild": type("Guild", (), {"id": 123})(),
            "channel": Channel(),
            "mentions": [],
            "reference": None,
        },
    )()
    monkeypatch.setattr(
        misc_tools,
        "parse_shorekeeper_trigger",
        lambda _bot, _message: {"keyword": "setowner", "extra": "add 111", "target": None, "args": []},
    )

    updates = []
    monkeypatch.setattr(misc_tools, "update_guild_config", lambda *_args: updates.append(_args))

    cog = misc_tools.MiscToolsCog.__new__(misc_tools.MiscToolsCog)
    cog.bot = type("Bot", (), {"user": type("BotUser", (), {"id": 999})()})()

    async def no_fun_lock(_message):
        return False

    cog._enforce_fun_locks = no_fun_lock
    cog.afk = EmptyCollection()

    await misc_tools.MiscToolsCog.on_message(cog, message)

    assert updates == []
    assert any("sole owner" in (content or "").lower() for content, _kwargs in message.channel.sent)