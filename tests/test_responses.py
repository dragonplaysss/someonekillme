def test_sole_owner_id_is_exactly_configured_owner():
    from cogs.core.constants import SOLE_OWNER_ID

    assert SOLE_OWNER_ID == 708390973712891976


def test_permission_denial_response_has_clear_security_copy():
    from cogs.core.responses import response_engine
    from datetime import datetime

    embed = response_engine.permission_denied("You are not authorized to use this command.")

    # Check that title contains "Permission Denied" (may have emoji prefix)
    assert "Permission Denied" in embed.title
    assert "not authorized" in embed.description
    # Check footer starts with "Shorekeeper • Today at" (dynamic time)
    assert embed.footer.text.startswith("Shorekeeper • Today at")