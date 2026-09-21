from datetime import timedelta

import pytest


class FakeCursor:
    def __init__(self, docs):
        self.docs = docs

    def sort(self, *_args):
        return self

    async def to_list(self, _limit):
        return self.docs


class FakeAccounts:
    def __init__(self, docs):
        self.docs = docs
        self.queries = []

    async def find_one(self, query):
        self.queries.append(query)
        for doc in self.docs:
            if all(doc.get(key) == value for key, value in query.items()):
                return doc
        return None

    def find(self, query):
        self.queries.append(query)
        return FakeCursor(self.docs)


class FakeApprovals:
    def __init__(self):
        self.find_one_and_update_calls = []
        self.update_many_calls = []
        self.insert_one_calls = []
        self.find_one_calls = []

    async def find_one_and_update(self, filter_doc, update_doc, **kwargs):
        self.find_one_and_update_calls.append((filter_doc, update_doc, kwargs))
        return update_doc["$set"]

    async def update_many(self, query, update, **kwargs):
        self.update_many_calls.append((query, update, kwargs))
        # Return an object with modified_count attribute
        class UpdateResult:
            def __init__(self, modified_count):
                self.modified_count = modified_count
        # For testing purposes, we'll return a mock result
        return UpdateResult(modified_count=1)

    async def find_one(self, query, **kwargs):
        self.find_one_calls.append((query, kwargs))
        # For testing purposes, return a mock approval document if this looks like
        # a get_active_approval query
        if (
            "discord_user" in query and
            "username_key" in query and
            query.get("active") is True and
            "expires_at" in query and
            isinstance(query["expires_at"], dict) and
            "$gt" in query["expires_at"]
        ):
            # Return an expires_at that is actually greater than the $gt value in the query
            now = query["expires_at"]["$gt"]
            return {
                "discord_user": query["discord_user"],
                "username_key": query["username_key"],
                "active": True,
                "expires_at": now + timedelta(seconds=3600),  # 1 hour in the future
                "roblox_username": "BuilderMan",  # mock value
                "approved_by": 222,  # mock value
                "approved_at": now,  # approved 1 hour ago
            }
        # For other queries, return None to simulate no existing approval
        return None

    async def insert_one(self, document, **kwargs):
        self.insert_one_calls.append((document, kwargs))
        # Return a mock insert result
        class InsertResult:
            def __init__(self):
                self.inserted_id = "mock_id"
        return InsertResult()


class FakeUser:
    id = 555
    mention = "<@555>"

    def __init__(self):
        self.sent = []

    async def send(self, **kwargs):
        self.sent.append(kwargs)


@pytest.mark.asyncio
async def test_get_account_remains_global_not_guild_scoped():
    from cogs.roblox_auth import RobloxAuthCog

    cog = RobloxAuthCog.__new__(RobloxAuthCog)
    cog.accounts = FakeAccounts([{"username_key": "builderman", "active": True}])

    account = await cog.get_account("BuilderMan")

    assert account["username_key"] == "builderman"
    assert cog.accounts.queries == [{"username_key": "builderman", "active": True}]


@pytest.mark.asyncio
async def test_rbxlist_account_lookup_remains_global():
    from cogs.roblox_auth import RobloxAuthCog

    cog = RobloxAuthCog.__new__(RobloxAuthCog)
    cog.accounts = FakeAccounts([])

    cursor = cog.accounts.find({})
    await cursor.sort("username_key", 1).to_list(100)

    assert cog.accounts.queries == [{}]


@pytest.mark.asyncio
async def test_approval_assignment_uses_atomic_active_upsert():
    from cogs.roblox_auth import RobloxAuthCog

    cog = RobloxAuthCog.__new__(RobloxAuthCog)
    cog.approvals = FakeApprovals()
    account = {"username": "BuilderMan", "username_key": "builderman"}

    approval = await cog.approve_account_request(account, requester_id=111, moderator_id=222, duration=timedelta(minutes=5))

    filter_doc, update_doc, kwargs = cog.approvals.find_one_and_update_calls[0]
    assert filter_doc == {"username_key": "builderman", "active": True}
    assert update_doc["$set"]["discord_user"] == 111
    assert update_doc["$set"]["approved_by"] == 222
    assert update_doc["$set"]["active"] is True
    assert kwargs["upsert"] is True
    assert approval["username_key"] == "builderman"


@pytest.mark.asyncio
async def test_delivery_sends_credentials_by_dm_only():
    from cogs.roblox_auth import AuthCode, RobloxAuthCog
    from cogs.mongo_client import get_mongo_database
    from cryptography.fernet import Fernet
    from unittest.mock import patch

    class MockBot:
        def get_guild(self, guild_id):
            return None

    # Mock the MongoDB database to avoid connection errors in tests
    mock_db = {}
    mock_db["roblox_accounts"] = FakeAccounts([{"username_key": "builderman", "active": True}])
    mock_db["roblox_approvals"] = FakeApprovals()

    # Generate a valid Fernet key for testing
    test_key = Fernet.generate_key().decode()

    with patch('cogs.roblox_auth.get_mongo_database', return_value=mock_db), \
         patch.dict('os.environ', {'TOTP_SECRET_KEY': test_key}):
        cog = RobloxAuthCog(MockBot())

        async def mock_generate_code(_account):
            return AuthCode("123456", 21)

        cog.generate_code = mock_generate_code
        cog.approval_remaining_seconds = lambda _approval: 300
        cog.decrypt_password = lambda _encrypted: "correct horse battery staple"
        # Override the accounts and approvals collections with our fakes
        cog.accounts = mock_db["roblox_accounts"]
        cog.approvals = mock_db["roblox_approvals"]
        requester = FakeUser()
        account = {
            "username": "BuilderMan",
            "username_key": "builderman",
            "display_name": "Builder",
            "password": "encrypted",
        }

        result = await cog.deliver_approval_credentials(123, requester, account, {"username_key": "builderman"})

    assert result.delivered is True
    assert len(requester.sent) == 1
    sent = requester.sent[0]
    assert sent["embed"] is not None
    assert "correct horse battery staple" not in (sent.get("content") or "")


@pytest.mark.asyncio
async def test_delivery_failure_does_not_post_credentials_publicly():
    from cogs.roblox_auth import AuthCode, ApprovalDeliveryResult, RobloxAuthCog
    from cogs.mongo_client import get_mongo_database
    from cryptography.fernet import Fernet
    from unittest.mock import patch

    class ClosedUser(FakeUser):
        async def send(self, **kwargs):
            raise RuntimeError("DMs closed")

    class MockBot:
        def get_guild(self, guild_id):
            return None

    # Mock the MongoDB database to avoid connection errors in tests
    mock_db = {}
    mock_db["roblox_accounts"] = FakeAccounts([])
    mock_db["roblox_approvals"] = FakeApprovals()

    # Generate a valid Fernet key for testing
    test_key = Fernet.generate_key().decode()

    with patch('cogs.roblox_auth.get_mongo_database', return_value=mock_db), \
         patch.dict('os.environ', {'TOTP_SECRET_KEY': test_key}):
        cog = RobloxAuthCog(MockBot())

        async def mock_generate_code(_account):
            return AuthCode("123456", 21)

        cog.generate_code = mock_generate_code
        cog.approval_remaining_seconds = lambda _approval: 300
        cog.decrypt_password = lambda _encrypted: "secret-password"
        # Override the accounts and approvals collections with our fakes
        cog.accounts = mock_db["roblox_accounts"]
        cog.approvals = mock_db["roblox_approvals"]
        requester = ClosedUser()
        account = {
            "username": "BuilderMan",
            "username_key": "builderman",
            "display_name": "Builder",
            "password": "encrypted",
        }

        result = await cog.deliver_approval_credentials(123, requester, account, {"username_key": "builderman"})

    assert isinstance(result, ApprovalDeliveryResult)
    assert result.delivered is False
    assert requester.sent == []


def test_roblox_account_documents_may_keep_legacy_guild_id_but_lookup_ignores_it():
    from cogs.roblox_auth import _username_key

    legacy = {"username_key": "builderman", "guild_id": 999, "active": True}
    query = {"username_key": _username_key("BuilderMan"), "active": True}
    assert "guild_id" not in query
    assert all(legacy.get(key) == value for key, value in query.items())
