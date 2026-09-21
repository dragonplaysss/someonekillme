import pytest


def test_log_sanitizer_redacts_credentials():
    from cogs.logger import sanitize_log_content

    content = (
        "login password=CorrectHorseBatteryStaple "
        "totp secret JBSWY3DPEHPK3PXP "
        "token mfa.AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA "
        "https://discord.com/api/webhooks/123456/super-secret-webhook-token"
    )

    sanitized = sanitize_log_content(content)

    assert "CorrectHorseBatteryStaple" not in sanitized
    assert "JBSWY3DPEHPK3PXP" not in sanitized
    assert "mfa.AAAAAAAAA" not in sanitized
    assert "super-secret-webhook-token" not in sanitized
    assert "[REDACTED]" in sanitized


@pytest.mark.asyncio
async def test_logs_command_denies_non_staff(monkeypatch):
    import cogs.logger as logger_module

    class Ctx:
        guild = type("Guild", (), {"id": 123})()
        author = object()

        def __init__(self):
            self.sent = []

        async def send(self, *args, **kwargs):
            self.sent.append((args, kwargs))

    monkeypatch.setattr(logger_module, "can_access_logs", lambda _member: False, raising=False)
    ctx = Ctx()

    await logger_module.ServerLogger.logs.callback(logger_module.ServerLogger(None), ctx)

    assert ctx.sent
    assert "permission" in ctx.sent[0][0][0].lower()
    assert "file" not in ctx.sent[0][1]
