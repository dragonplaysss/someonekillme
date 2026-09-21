def test_module_registry_imports():
    import cogs.module_registry as registry

    assert registry.CORE_MODULE == "core"
    assert "moderation" in registry.MODULES


def test_server_config_owner_constant_is_current_value():
    from cogs.server_config import PANEL_OWNER_ID

    assert PANEL_OWNER_ID == 708390973712891976
