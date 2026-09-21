import os

from motor.motor_asyncio import AsyncIOMotorClient


_client = None


def get_mongo_database():
    global _client

    mongo_uri = os.getenv("MONGODB_URI")
    if not mongo_uri:
        raise RuntimeError("MONGODB_URI is missing. Set it in your .env file.")

    db_name = os.getenv("MONGODB_DB", "shorekeeper")
    if _client is None:
        _client = AsyncIOMotorClient(mongo_uri)

    return _client[db_name]


async def safe_create_index(collection, keys, *, label=None, **options) -> bool:
    """Create an index without ever letting the failure kill a cog load.

    Index setup is an optimisation, not a security boundary. A rejected index
    specification (for example MongoDB code 197 for ``unique`` on ``_id``) or a
    transient database error must never prevent a cog from registering its
    listeners, because that silently disables working commands.
    """
    name = label or getattr(collection, "name", "collection")
    try:
        await collection.create_index(keys, **options)
        return True
    except Exception as exc:  # noqa: BLE001 - index failures must stay non-fatal
        print(f"[MONGO] index setup failed for {name} keys={keys}: {type(exc).__name__}: {exc}")
        return False
