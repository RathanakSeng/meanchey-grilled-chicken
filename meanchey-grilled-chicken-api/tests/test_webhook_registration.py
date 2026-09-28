"""setWebhook is only called when needed; Telegram outages never break startup."""

import pytest
from aiogram.types import WebhookInfo
from sqlalchemy import select

from app.bootstrap import bootstrap
from app.bot.registration import FINGERPRINT_KEY, ensure_webhook
from app.bot.runtime import TelegramRuntime
from app.bot.setup import create_bot, create_dispatcher
from app.config import get_settings
from app.models import AppSetting, Role, User
from tests.telegram_fakes import RecordingSession

URL = "https://bot.example.com/api/telegram/webhook"
SECRET = "registration_secret-1"


@pytest.fixture
def webhook_settings(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "bot_mode", "webhook")
    monkeypatch.setattr(s, "telegram_webhook_url", URL)
    monkeypatch.setattr(s, "telegram_webhook_secret", SECRET)
    monkeypatch.setattr(s, "telegram_webhook_auto_set", True)
    monkeypatch.setattr(s, "telegram_drop_pending_updates", False)
    return s


def _registered(url: str = URL, allowed: list[str] | None = None) -> WebhookInfo:
    return WebhookInfo(
        url=url,
        has_custom_certificate=False,
        pending_update_count=0,
        allowed_updates=allowed if allowed is not None else ["message"],
    )


async def test_sets_webhook_when_none_registered(session, webhook_settings) -> None:
    tg = RecordingSession()
    bot, dp = create_bot(session=tg), create_dispatcher()
    assert await ensure_webhook(bot, dp, session) is True
    await session.commit()

    (call,) = tg.calls("SetWebhook")
    assert call.url == URL
    assert call.secret_token == SECRET
    assert call.allowed_updates == ["message"]
    assert call.drop_pending_updates is False
    assert tg.calls("SetMyCommands")
    assert await session.get(AppSetting, FINGERPRINT_KEY) is not None


async def test_skips_when_already_up_to_date(session, webhook_settings) -> None:
    # First registration stores the fingerprint…
    await ensure_webhook(create_bot(session=RecordingSession()), create_dispatcher(), session)
    await session.commit()
    # …then Telegram reports the same URL / updates: nothing to do.
    tg = RecordingSession(responses={"GetWebhookInfo": _registered()})
    assert await ensure_webhook(create_bot(session=tg), create_dispatcher(), session) is False
    assert tg.calls("SetWebhook") == []


async def test_resets_when_url_differs(session, webhook_settings) -> None:
    await ensure_webhook(create_bot(session=RecordingSession()), create_dispatcher(), session)
    await session.commit()
    tg = RecordingSession(
        responses={"GetWebhookInfo": _registered(url="https://old.example.com/x")}
    )
    assert await ensure_webhook(create_bot(session=tg), create_dispatcher(), session) is True
    assert tg.calls("SetWebhook")[0].url == URL


async def test_resets_when_secret_changes(session, webhook_settings, monkeypatch) -> None:
    await ensure_webhook(create_bot(session=RecordingSession()), create_dispatcher(), session)
    await session.commit()
    # Telegram can't tell us the secret; the stored fingerprint detects the change.
    monkeypatch.setattr(webhook_settings, "telegram_webhook_secret", "rotated_secret-2")
    tg = RecordingSession(responses={"GetWebhookInfo": _registered()})
    assert await ensure_webhook(create_bot(session=tg), create_dispatcher(), session) is True
    assert tg.calls("SetWebhook")[0].secret_token == "rotated_secret-2"


async def test_resets_when_allowed_updates_differ(session, webhook_settings) -> None:
    await ensure_webhook(create_bot(session=RecordingSession()), create_dispatcher(), session)
    await session.commit()
    tg = RecordingSession(responses={"GetWebhookInfo": _registered(allowed=["message", "poll"])})
    assert await ensure_webhook(create_bot(session=tg), create_dispatcher(), session) is True


async def test_telegram_unreachable_does_not_break_bootstrap(
    session, webhook_settings, caplog
) -> None:
    tg = RecordingSession(unreachable=True)
    runtime = TelegramRuntime(bot=create_bot(session=tg), dp=create_dispatcher(), secret=SECRET)
    await bootstrap(session, runtime)  # must not raise

    assert tg.calls("GetWebhookInfo")
    assert "could not register the Telegram webhook" in caplog.text
    # The rest of bootstrap still ran and committed.
    assert await session.scalar(select(User.id).where(User.role == Role.SUPERADMIN))
    assert await session.get(AppSetting, FINGERPRINT_KEY) is None


async def test_bootstrap_skips_registration_when_auto_set_off(
    session, webhook_settings, monkeypatch
) -> None:
    monkeypatch.setattr(webhook_settings, "telegram_webhook_auto_set", False)
    tg = RecordingSession()
    runtime = TelegramRuntime(bot=create_bot(session=tg), dp=create_dispatcher(), secret=SECRET)
    await bootstrap(session, runtime)
    assert tg.requests == []


async def test_bootstrap_skips_registration_in_polling_mode(
    session, webhook_settings, monkeypatch
) -> None:
    monkeypatch.setattr(webhook_settings, "bot_mode", "polling")
    tg = RecordingSession()
    runtime = TelegramRuntime(bot=create_bot(session=tg), dp=create_dispatcher(), secret=SECRET)
    await bootstrap(session, runtime)
    assert tg.requests == []
