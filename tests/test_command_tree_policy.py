def test_core_slash_tree_remains_small():
    from cogs.module_registry import MODULES, RETIRED_MODULES

    core = set(MODULES["core"]["slash"])
    assert {"help", "settings", "status", "enablecommands", "disablecommands"}.issubset(core)
    assert "ban" not in core
    assert "kick" not in core
    assert "warn" not in core
    for module in RETIRED_MODULES:
        assert MODULES[module].get("retired") is True
        assert not MODULES[module].get("extension")
