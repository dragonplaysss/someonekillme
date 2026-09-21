import asyncio

import pytest


def test_redacts_discord_token_like_value():
    from cogs.core.redaction import redact_sensitive

    text = "token abc.def.ghi password hunter2"
    redacted = redact_sensitive(text)

    assert "abc.def.ghi" not in redacted
    assert "hunter2" not in redacted
    assert "[REDACTED]" in redacted


def test_redacts_webhook_urls_and_totp_secrets():
    from cogs.core.redaction import redact_sensitive

    text = (
        "https://discord.com/api/webhooks/123456/abcDEF-xyz "
        "totp secret JBSWY3DPEHPK3PXP "
        "Authorization: Bearer abcdefghijklmnopqrstuvwxyz012345"
    )
    redacted = redact_sensitive(text)

    assert "abcDEF-xyz" not in redacted
    assert "JBSWY3DPEHPK3PXP" not in redacted
    assert "abcdefghijklmnopqrstuvwxyz012345" not in redacted
    assert redacted.count("[REDACTED]") >= 3


def test_redaction_handles_empty_values():
    from cogs.core.redaction import redact_sensitive

    assert redact_sensitive(None) == ""
    assert redact_sensitive("") == ""


def test_logger_sanitizer_defers_to_the_canonical_redactor():
    from cogs.core.redaction import redact_sensitive
    from cogs.logger import sanitize_log_content

    text = "token abc.def.ghi"

    assert sanitize_log_content(text) == redact_sensitive(text)
    assert sanitize_log_content(None) is None


def test_log_entries_are_redacted_on_write(tmp_path, monkeypatch):
    import cogs.logger as logger_module

    monkeypatch.setattr(logger_module, "LOG_FOLDER", str(tmp_path))
    logger_module.add_log(123, {"content": "password hunter2", "before": "totp secret JBSWY3DPEHPK3PXP"})

    stored = logger_module.load_logs(123)
    assert "hunter2" not in str(stored)
    assert "JBSWY3DPEHPK3PXP" not in str(stored)
    assert "[REDACTED]" in str(stored)


@pytest.mark.asyncio
async def test_log_writes_are_atomic(tmp_path, monkeypatch):
    import cogs.logger as logger_module

    monkeypatch.setattr(logger_module, "LOG_FOLDER", str(tmp_path))

    await asyncio.gather(*(asyncio.to_thread(logger_module.add_log, 123, {"content": f"entry {i}"}) for i in range(5)))

    stored = logger_module.load_logs(123)
    assert len(stored) == 5
    leftovers = [path.name for path in tmp_path.iterdir() if path.suffix != ".json"]
    assert leftovers == []