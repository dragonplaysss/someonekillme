import pytest


@pytest.mark.asyncio
async def test_config_service_creates_guild_with_expected_defaults(tmp_path):
    from cogs.core.config import ConfigService

    service = ConfigService(tmp_path / "server_config.json")
    cfg = await service.get_guild_config(123)

    assert cfg["modules"] == {}
    assert cfg["enabled"] is False
    assert "owner_ids" not in cfg


@pytest.mark.asyncio
async def test_config_service_preserves_legacy_values_without_owner_authority(tmp_path):
    from cogs.core.config import ConfigService

    path = tmp_path / "server_config.json"
    path.write_text(
        '{"guilds":{"123":{"owner_ids":[1],"modules":{"moderation":"active"}}}}',
        encoding="utf-8",
    )
    service = ConfigService(path)
    cfg = await service.get_guild_config(123)

    assert cfg["owner_ids"] == [1]
    assert cfg["modules"]["moderation"] == "active"
    assert cfg["enabled"] is False
