def test_lockdown_helpers_are_reversible():
    from cogs.core.lockdown import activate_lockdown, deactivate_lockdown, is_lockdown_active

    config = {"lockdown": {"enabled": False, "channel_ids": [1]}}
    activate_lockdown(config, 708390973712891976, channel_ids=[1, 2])
    assert is_lockdown_active(config) is True
    assert config["lockdown"]["activated_by"] == 708390973712891976
    deactivate_lockdown(config)
    assert is_lockdown_active(config) is False
