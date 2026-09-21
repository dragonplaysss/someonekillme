import pytest

from tests.conftest import FakePermissions, FakeRole


class FakeMember:
    def __init__(self, user_id, position, *, roles=None):
        self.id = user_id
        self.top_role = FakeRole(position, user_id, f"role-{user_id}")
        self.guild_permissions = FakePermissions()
        self.roles = roles or []
        self.mention = f"<@{user_id}>"
        self.edits = []

    async def edit(self, **kwargs):
        self.edits.append(kwargs)


class FakeGuild:
    id = 123

    def __init__(self, roles):
        self._roles = {role.id: role for role in roles}

    def get_role(self, role_id):
        return self._roles.get(role_id)


@pytest.fixture
def seal_cog(monkeypatch):
    import cogs.moderation.seal as seal_module

    stored = {}

    monkeypatch.setattr(seal_module, "load_data", lambda: stored.setdefault("data", {}))
    monkeypatch.setattr(seal_module, "save_data", lambda data: stored.update({"data": data}))

    cog = seal_module.Seal.__new__(seal_module.Seal)
    cog.bot = None
    return cog


def prepare(cog, *, bot_position, guild_roles, member_roles, seal_role):
    member = FakeMember(7, 1, roles=list(member_roles))
    guild = FakeGuild([seal_role, *guild_roles])
    member.guild = guild
    bot_member = FakeMember(9, bot_position)

    cog.get_bot_member = lambda _guild: bot_member
    cog.validate_can_manage_member = lambda _member: None
    cog.validate_can_use_role = lambda _guild, _role: None

    async def get_seal_role(_guild):
        return seal_role

    cog.get_seal_role = get_seal_role
    cog.get_guild_data = lambda data, guild_id: data.setdefault(str(guild_id), {})
    return member


@pytest.mark.asyncio
async def test_seal_refuses_before_api_call_when_a_role_is_above_the_bot(seal_cog):
    seal_role = FakeRole(1, 100, "sealed")
    high_role = FakeRole(50, 200, "high")
    member = prepare(
        seal_cog,
        bot_position=10,
        guild_roles=[high_role],
        member_roles=[high_role],
        seal_role=seal_role,
    )

    success, detail = await seal_cog.seal_member(member)

    assert success is False
    assert "equal to or above" in detail
    assert "high" in detail
    assert member.edits == []


@pytest.mark.asyncio
async def test_seal_records_only_manageable_roles(seal_cog):
    seal_role = FakeRole(1, 100, "sealed")
    low_role = FakeRole(2, 201, "low")
    member = prepare(
        seal_cog,
        bot_position=10,
        guild_roles=[low_role],
        member_roles=[low_role],
        seal_role=seal_role,
    )

    success, detail = await seal_cog.seal_member(member)

    assert success is True
    assert detail is None
    assert member.edits and member.edits[0]["roles"] == [seal_role]


@pytest.mark.asyncio
async def test_unseal_skips_roles_equal_to_or_above_the_bot(seal_cog):
    import cogs.moderation.seal as seal_module

    seal_role = FakeRole(1, 100, "sealed")
    low_role = FakeRole(2, 201, "low")
    high_role = FakeRole(50, 202, "high")
    member = prepare(
        seal_cog,
        bot_position=10,
        guild_roles=[low_role, high_role],
        member_roles=[],
        seal_role=seal_role,
    )

    data = seal_module.load_data()
    data[str(member.guild.id)] = {str(member.id): [low_role.id, high_role.id]}

    success, detail = await seal_cog.unseal_member(member)

    assert success is True
    assert "high" in detail
    assert member.edits and member.edits[0]["roles"] == [low_role]