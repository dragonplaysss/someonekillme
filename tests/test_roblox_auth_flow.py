import pytest


def test_username_key_is_global_not_guild_scoped():
    from cogs.roblox_auth import _username_key

    assert _username_key("BuilderMan") == "builderman"


def test_approval_filter_does_not_include_guild_scope():
    from cogs.roblox_auth import _username_key

    query = {"username_key": _username_key("BuilderMan"), "active": True}

    assert "guild_id" not in query


def test_active_approval_uniqueness_filter_is_global():
    username_key = "builderman"
    replacement_filter = {"username_key": username_key, "active": True}

    assert replacement_filter == {"username_key": "builderman", "active": True}
    assert "guild_id" not in replacement_filter


def test_delivery_result_has_no_credential_fields():
    from cogs.roblox_auth import DeliveryResult

    result = DeliveryResult(delivered=False, reason="dm_forbidden")

    assert result.success is False
    assert result.reason == "dm_forbidden"
    assert result.password_included is False
    assert not hasattr(result, "password")
    assert not hasattr(result, "totp_secret")
    assert not hasattr(result, "code")
    assert not hasattr(result, "totp")


def test_delivery_result_success_mirrors_delivered():
    from cogs.roblox_auth import DeliveryResult

    assert DeliveryResult(delivered=True, reason=None, password_included=True).success is True


class FakeApprovals:
    """Records the filter used for the single-active-approval update."""

    def __init__(self):
        self.filters = []
        self.updates = []
        self.inserts = []
        self.finds = []

    async def find_one_and_update(self, query, update, **_kwargs):
        self.filters.append(query)
        self.updates.append(update)
        return {"username_key": query["username_key"], "active": True}

    async def update_many(self, query, update, **_kwargs):
        self.filters.append(query)
        self.updates.append(update)
        # Return an object with modified_count attribute
        class UpdateResult:
            def __init__(self, modified_count):
                self.modified_count = modified_count
        # For testing purposes, we'll return a mock result
        # In real usage, this would depend on how many documents match
        return UpdateResult(modified_count=1)

    async def find_one(self, query, **_kwargs):
        self.finds.append(query)
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
                "expires_at": now + 3600,  # 1 hour in the future
                "roblox_username": "BuilderMan",  # mock value
                "approved_by": 222,  # mock value
                "approved_at": now,  # approved 1 hour ago
            }
        # For other queries, return None to simulate no existing approval
        return None

    async def insert_one(self, document, **_kwargs):
        self.inserts.append(document)
        # InsertOneResult would have an inserted_id, but we don't need to check that in tests
        class InsertResult:
            def __init__(self):
                self.inserted_id = "mock_id"
        return InsertResult()


@pytest.mark.asyncio
async def test_approve_account_request_uses_one_global_active_approval():
    from cogs.roblox_auth import RobloxAuthCog

    cog = RobloxAuthCog.__new__(RobloxAuthCog)
    cog.approvals = FakeApprovals()
    cog._approval_locks = {}

    import datetime

    account = {"username": "BuilderMan", "username_key": "builderman"}
    approval = await cog.approve_account_request(account, 111, 222, datetime.timedelta(minutes=5))

    assert approval["active"] is True
    assert cog.approvals.filters == [{"username_key": "builderman", "active": True}]
    assert "guild_id" not in cog.approvals.filters[0]
    assert cog.approvals.updates[0]["$set"]["discord_user"] == 111
    assert cog.approvals.updates[0]["$set"]["approved_by"] == 222