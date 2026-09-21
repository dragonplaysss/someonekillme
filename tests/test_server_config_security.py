import json


def test_server_config_owner_ids_are_preserved_but_not_authoritative(tmp_path, monkeypatch):
    import cogs.server_config as server_config

    config_path = tmp_path / "server_config.json"
    config_path.write_text(
        json.dumps(
            {
                "guilds": {
                    "123": {
                        "owner_ids": [111],
                        "admin_ids": [],
                        "admin_roles": [],
                        "mod_roles": [],
                    }
                },
                "roblox_auth": {"authorized_guild_ids": []},
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(server_config, "CONFIG_PATH", str(config_path))
    monkeypatch.setattr(server_config, "_CONFIG_CACHE", None)
    monkeypatch.setattr(server_config, "_CONFIG_MTIME", None)

    cfg = server_config.get_guild_config(123)
    assert cfg["owner_ids"] == [111]
    assert server_config.is_owner_id(123, 111) is False
    assert server_config.is_owner_id(123, 708390973712891976) is True
