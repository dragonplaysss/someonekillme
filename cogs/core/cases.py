from __future__ import annotations

import discord
from pymongo import ReturnDocument


class CaseService:
    def __init__(self, db):
        self.cases = db["moderation_cases"]
        self.counters = db["moderation_case_counters"]

    async def _ensure_index(self, collection, keys, **options) -> bool:
        try:
            await collection.create_index(keys, **options)
            return True
        except Exception as exc:  # noqa: BLE001 - index setup must never be fatal
            print(f"[CASES] index setup failed for keys={keys}: {type(exc).__name__}: {exc}")
            return False

    async def ensure_indexes(self):
        """Create the case indexes without ever raising.

        MongoDB already enforces uniqueness on ``_id`` and rejects an explicit
        ``unique`` index specification for it (code 197
        ``InvalidIndexSpecificationOption``). Requesting it used to abort cog
        loading and silently disable all of moderation, so the ``_id`` index is
        never requested here and every index failure is reported instead of
        propagated.
        """
        await self._ensure_index(self.cases, [("guild_id", 1), ("case_id", 1)], unique=True)
        await self._ensure_index(
            self.cases, [("guild_id", 1), ("target_id", 1), ("created_at", -1)]
        )

    async def next_case_id(self, guild_id: int) -> int:
        counter = await self.counters.find_one_and_update(
            {"_id": int(guild_id)},
            {"$inc": {"seq": 1}},
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
        return int((counter or {}).get("seq") or 0)

    async def create_case(
        self,
        *,
        guild_id: int,
        action: str,
        target_id: int,
        moderator_id: int,
        reason: str,
        evidence: str | None = None,
    ) -> dict:
        case_id = await self.next_case_id(guild_id)
        doc = {
            "guild_id": int(guild_id),
            "case_id": case_id,
            "action": (action or "ACTION").upper(),
            "target_id": int(target_id),
            "moderator_id": int(moderator_id),
            "reason": reason or "No reason provided.",
            "evidence": evidence,
            "created_at": discord.utils.utcnow(),
        }
        await self.cases.insert_one(doc)
        return doc

    async def find_case(self, guild_id: int, case_id: int):
        return await self.cases.find_one({"guild_id": int(guild_id), "case_id": int(case_id)})

    async def find_cases(self, guild_id: int, target_id: int, limit: int = 10):
        cursor = self.cases.find({"guild_id": int(guild_id), "target_id": int(target_id)}).sort("created_at", -1)
        if hasattr(cursor, "to_list"):
            return await cursor.to_list(limit)
        docs = []
        async for doc in cursor:
            docs.append(doc)
            if len(docs) >= limit:
                break
        return docs
