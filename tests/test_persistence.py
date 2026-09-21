import asyncio

import pytest


@pytest.mark.asyncio
async def test_json_store_preserves_concurrent_updates(tmp_path):
    from cogs.core.persistence import JsonStore

    store = JsonStore(tmp_path / "config.json", lambda: {"count": 0, "items": []})

    async def add_item(value):
        async def mutate(data):
            data["count"] += 1
            data["items"].append(value)

        await store.update(mutate)

    await asyncio.gather(*(add_item(i) for i in range(10)))
    data = await store.read()

    assert data["count"] == 10
    assert sorted(data["items"]) == list(range(10))
def test_atomic_write_json_replaces_content_without_leftover_temp_files(tmp_path):
    import json

    from cogs.core.persistence import atomic_write_json

    target = tmp_path / "nested" / "state.json"
    atomic_write_json(target, {"a": 1})
    atomic_write_json(target, {"a": 2})

    assert json.loads(target.read_text(encoding="utf-8")) == {"a": 2}
    assert [path.name for path in target.parent.iterdir()] == ["state.json"]


def test_atomic_write_json_never_leaves_a_partial_document(tmp_path):
    import json

    from cogs.core.persistence import atomic_write_json

    target = tmp_path / "state.json"
    target.write_text(json.dumps({"old": True}), encoding="utf-8")

    class Unserializable:
        pass

    with pytest.raises(TypeError):
        atomic_write_json(target, {"bad": Unserializable()})

    # The previous complete document survives a failed write.
    assert json.loads(target.read_text(encoding="utf-8")) == {"old": True}
    assert [path.name for path in tmp_path.iterdir()] == ["state.json"]


@pytest.mark.asyncio
async def test_json_store_recovers_from_corrupt_file(tmp_path):
    from cogs.core.persistence import JsonStore

    path = tmp_path / "config.json"
    path.write_text("{not json", encoding="utf-8")

    store = JsonStore(path, lambda: {"count": 0})

    assert await store.read() == {"count": 0}
    assert (tmp_path / "config.json.corrupt").exists()


@pytest.mark.asyncio
async def test_json_store_update_is_visible_to_later_reads(tmp_path):
    from cogs.core.persistence import JsonStore

    store = JsonStore(tmp_path / "config.json", lambda: {"count": 0})

    async def mutate(data):
        data["count"] += 1

    await store.update(mutate)
    await store.update(mutate)

    assert await store.read() == {"count": 2}
