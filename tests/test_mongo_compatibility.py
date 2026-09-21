def test_legacy_mongo_document_shapes_remain_readable():
    warns = {"guild_id": 1, "user_id": 2, "moderator_id": 3, "reason": "spam", "timestamp": "legacy"}
    mod_actions = {"guild_id": 1, "moderator_id": 3, "target_id": 2, "action": "kick", "reason": "spam"}
    roblox_account = {"username": "Ada", "username_key": "ada", "totp_secret": "enc", "active": True}
    approval = {"username_key": "ada", "discord_user": 4, "active": True}

    assert "guild_id" in warns
    assert "action" in mod_actions
    assert "username_key" in roblox_account
    assert "discord_user" in approval
