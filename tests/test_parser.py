class FakeBotUser:
    id = 42

    def mentioned_in(self, _message):
        return True


class FakeBot:
    user = FakeBotUser()


class FakeGuild:
    id = 123

    def get_member(self, user_id):
        return type("Member", (), {"id": user_id, "mention": f"<@{user_id}>"})()

    def get_channel(self, channel_id):
        return type("Channel", (), {"id": channel_id, "mention": f"<#{channel_id}>"})()

    def get_role(self, role_id):
        return type("Role", (), {"id": role_id, "mention": f"<@&{role_id}>"})()


class FakeMessage:
    def __init__(self, content, *, author_id=99, mentions=None):
        self.content = content
        self.author = type("Author", (), {"id": author_id, "bot": False})()
        self.guild = FakeGuild()
        self.mentions = mentions or []
        self.channel_mentions = []
        self.role_mentions = []


def test_parser_supports_mentions_quotes_ids_and_durations(monkeypatch):
    import cogs.core.parser as parser

    monkeypatch.setattr(
        parser,
        "get_guild_config",
        lambda _guild_id: {"enabled": True, "modules": {"moderation": "active"}},
    )
    message = FakeMessage('<@42> ban <@99> 10m "raid attempt"')
    mentioned = type("User", (), {"id": 99, "mention": "<@99>"})()
    message.mentions = [FakeBotUser(), mentioned]

    parsed = parser.parse_shorekeeper_trigger(FakeBot(), message)

    assert parsed["keyword"] == "ban"
    assert parsed["target_id"] == 99
    assert parsed["duration"] == "10m"
    assert "raid attempt" in parsed["args"]


def test_parser_aliases_timeout_to_mute(monkeypatch):
    import cogs.core.parser as parser

    monkeypatch.setattr(
        parser,
        "get_guild_config",
        lambda _guild_id: {"enabled": True, "modules": {"moderation": "active"}},
    )
    parsed = parser.parse_shorekeeper_trigger(FakeBot(), FakeMessage("<@42> timeout 10m"))
    assert parsed["keyword"] == "mute"
    assert parsed["duration"] == "10m"


def test_parser_rejects_disabled_module(monkeypatch):
    import cogs.core.parser as parser

    monkeypatch.setattr(
        parser,
        "get_guild_config",
        lambda _guild_id: {"enabled": True, "modules": {"moderation": "disabled"}},
    )
    parsed = parser.parse_shorekeeper_trigger(FakeBot(), FakeMessage("<@42> ban 1"))
    assert parsed is None


def test_parser_blocks_disabled_guild_for_non_owner(monkeypatch):
    import cogs.core.parser as parser

    monkeypatch.setattr(parser, "get_guild_config", lambda _guild_id: {"enabled": False, "modules": {}})
    parsed = parser.parse_shorekeeper_trigger(FakeBot(), FakeMessage("<@42> ban 1", author_id=5))
    assert parsed["keyword"] == parser.INACTIVE_KEYWORD


def test_parser_allows_owner_guild_enable_when_disabled(monkeypatch):
    import cogs.core.parser as parser

    monkeypatch.setattr(parser, "get_guild_config", lambda _guild_id: {"enabled": False, "modules": {}})
    parsed = parser.parse_shorekeeper_trigger(
        FakeBot(),
        FakeMessage("<@42> guild enable", author_id=708390973712891976),
    )
    assert parsed["keyword"] == "guild"
    assert parsed["args"] == ["enable"]


def test_parser_channel_and_role_ids(monkeypatch):
    import cogs.core.parser as parser

    monkeypatch.setattr(
        parser,
        "get_guild_config",
        lambda _guild_id: {"enabled": True, "modules": {"moderation": "active"}},
    )
    parsed = parser.parse_shorekeeper_trigger(FakeBot(), FakeMessage("<@42> lock <#111111111111111111>"))
    assert parsed["keyword"] == "lock"
    assert parsed["channel_id"] == 111111111111111111
def test_pure_parser_exposes_keyword_args_user_ids_and_durations():
    from cogs.core.parser import parse_duration, parse_mention_command

    parsed = parse_mention_command(
        bot_user_id=999,
        content='<@999> ban <@123456789012345678> "raid attempt"',
    )

    assert parsed is not None
    assert parsed.keyword == "ban"
    assert parsed.module == "moderation"
    assert parsed.args == ["<@123456789012345678>", "raid attempt"]
    assert parsed.user_ids == [123456789012345678]

    assert parse_duration("10s").total_seconds() == 10
    assert parse_duration("10m").total_seconds() == 600
    assert parse_duration("2h").total_seconds() == 7200
    assert parse_duration("7d").total_seconds() == 604800
    assert parse_duration("nonsense") is None
    assert parse_duration(None) is None


def test_pure_parser_requires_the_bot_mention_first_and_a_keyword():
    from cogs.core.parser import parse_mention_command

    assert parse_mention_command(999, "ban <@123456789012345678>") is None
    assert parse_mention_command(999, "<@999>") is None
    assert parse_mention_command(999, "") is None


def test_pure_parser_supports_semicolon_and_aliases():
    from cogs.core.parser import parse_mention_command

    parsed = parse_mention_command(999, "<@999> timeout <@123456789012345678> 10m ; spamming")

    assert parsed.keyword == "mute"
    assert parsed.raw_keyword == "timeout"
    assert parsed.extra == "spamming"
    assert parsed.user_ids == [123456789012345678]


def test_compatibility_wrapper_exposes_user_ids(monkeypatch):
    import cogs.core.parser as parser

    monkeypatch.setattr(
        parser,
        "get_guild_config",
        lambda _guild_id: {"enabled": True, "modules": {"moderation": "active"}},
    )
    message = FakeMessage('<@42> ban <@99> 10m "raid attempt"')
    message.mentions = [FakeBotUser(), type("User", (), {"id": 99, "mention": "<@99>"})()]

    parsed = parser.parse_shorekeeper_trigger(FakeBot(), message)

    assert parsed["user_ids"] == [99]
    assert parsed["target_id"] == 99
