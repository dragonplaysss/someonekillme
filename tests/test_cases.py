import pytest


class FakeCollection:
    def __init__(self):
        self.docs = []
        self.seq = 0

    async def find_one_and_update(self, query, update, upsert=False, return_document=None):
        self.seq += int(update.get("$inc", {}).get("seq", 1))
        return {"_id": query["_id"], "seq": self.seq}

    async def insert_one(self, doc):
        self.docs.append(doc)
        return object()

    async def find_one(self, query):
        for doc in self.docs:
            if all(doc.get(key) == value for key, value in query.items()):
                return doc
        return None

    def find(self, query):
        matched = [doc for doc in self.docs if all(doc.get(key) == value for key, value in query.items())]

        class Cursor:
            def sort(self, *_args):
                return self

            async def to_list(self, limit):
                return matched[:limit]

        return Cursor()

    async def create_index(self, *_args, **_kwargs):
        return None


class FakeDb(dict):
    def __getitem__(self, key):
        self.setdefault(key, FakeCollection())
        return super().__getitem__(key)


@pytest.mark.asyncio
async def test_create_case_assigns_incrementing_case_id():
    from cogs.core.cases import CaseService

    db = FakeDb()
    service = CaseService(db)
    first = await service.create_case(
        guild_id=123,
        action="BAN",
        target_id=10,
        moderator_id=20,
        reason="Raid attempt",
        evidence=None,
    )
    second = await service.create_case(
        guild_id=123,
        action="WARN",
        target_id=10,
        moderator_id=20,
        reason="Follow-up",
    )

    assert first["case_id"] == 1
    assert second["case_id"] == 2
    assert db["moderation_cases"].docs[0]["target_id"] == 10
    found = await service.find_case(123, 1)
    assert found["action"] == "BAN"


@pytest.mark.asyncio
async def test_existing_warn_and_mod_action_collections_remain_separate():
    db = FakeDb()
    db["warns"].docs.append({"guild_id": 1, "user_id": 2, "reason": "legacy"})
    db["mod_actions"].docs.append({"guild_id": 1, "action": "kick"})
    assert db["warns"].docs[0]["reason"] == "legacy"
    assert db["mod_actions"].docs[0]["action"] == "kick"
    assert "moderation_cases" not in db or db["moderation_cases"].docs == []
