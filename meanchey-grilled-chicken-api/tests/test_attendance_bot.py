"""Attendance in the bot: the /start Attendance button (tracked employees only), no attendance
commands, the menu button at registration (fingerprint includes MINI_APP_URL) and per chat."""

import pytest

from app.bot.registration import ensure_webhook
from app.bot.runtime import TelegramRuntime
from app.bot.setup import BOT_COMMANDS, create_bot, create_dispatcher
from app.config import get_settings
from app.main import app
from app.models import Language, Role
from tests.telegram_fakes import RecordingSession, command_update

WEBHOOK = "http://test/api/telegram/webhook"
SECRET = "attendance_secret"
HEADERS = {"X-Telegram-Bot-Api-Secret-Token": SECRET}
MINI_APP = "https://meanchey.example.com"


@pytest.fixture
def tg(monkeypatch) -> RecordingSession:
    tg = RecordingSession()
    monkeypatch.setattr(get_settings(), "mini_app_url", MINI_APP)
    app.state.telegram = TelegramRuntime(
        bot=create_bot(session=tg), dp=create_dispatcher(), secret=SECRET
    )
    yield tg
    app.state.telegram = None


async def _command(client, text: str, tg_id: int) -> None:
    r = await client.post(WEBHOOK, json=command_update(text, tg_id=tg_id), headers=HEADERS)
    assert r.status_code == 200


def _buttons(sent) -> list[tuple[str, str]]:
    (row,) = sent.reply_markup.inline_keyboard
    return [(b.text, b.web_app.url) for b in row]


async def test_start_shows_attendance_for_tracked_employees(client, tg, make_user) -> None:
    await make_user(Role.STAFF, telegram_user_id=901)
    await _command(client, "/start", 901)
    (sent,) = tg.calls("SendMessage")
    assert _buttons(sent) == [
        ("🍗 បើកកម្មវិធី", MINI_APP),
        ("🕒 វត្តមាន", f"{MINI_APP}/attendance/check"),
    ]


async def test_start_in_english_for_supervisors(client, session, tg, make_user) -> None:
    sup = await make_user(Role.SUPERVISOR, telegram_user_id=902)
    sup.language = Language.EN
    await session.commit()
    await _command(client, "/start", 902)
    (sent,) = tg.calls("SendMessage")
    assert [text for text, _ in _buttons(sent)] == ["🍗 Open app", "🕒 Attendance"]


async def test_start_without_attendance(client, tg, make_user) -> None:
    """General managers, deactivated employees and unlinked chats only get Open app."""
    await make_user(Role.GENERAL_MANAGER, telegram_user_id=903)
    await make_user(Role.STAFF, telegram_user_id=904, is_active=False)
    for tg_id in (903, 904, 999):
        await _command(client, "/start", tg_id)
    for sent in tg.calls("SendMessage"):
        assert _buttons(sent) == [("🍗 បើកកម្មវិធី", MINI_APP)]


async def test_app_not_configured(client, tg, make_user, monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "mini_app_url", "http://localhost:5173")
    await make_user(Role.STAFF, telegram_user_id=905)
    await _command(client, "/start", 905)
    (sent,) = tg.calls("SendMessage")
    assert "⚠️ កម្មវិធីមិនទាន់បានកំណត់" in sent.text
    assert sent.reply_markup is None


async def test_no_attendance_commands(client, tg, make_user) -> None:
    await make_user(Role.STAFF, telegram_user_id=906)
    for text in ("/checkin", "/checkout"):
        await _command(client, text, 906)
    assert tg.calls("SendMessage") == []


async def test_start_and_lang_set_the_chat_menu_button(client, tg) -> None:
    await _command(client, "/start", 907)
    (menu,) = tg.calls("SetChatMenuButton")
    assert menu.chat_id == 907
    assert (menu.menu_button.text, menu.menu_button.web_app.url) == ("បើកកម្មវិធី", MINI_APP)
    await _command(client, "/lang", 907)
    menu = tg.calls("SetChatMenuButton")[-1]
    assert menu.menu_button.text == "Open app"


def test_commands_listed() -> None:
    assert [c.command for c in BOT_COMMANDS] == ["start", "lang"]


@pytest.fixture
def webhook_settings(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "bot_mode", "webhook")
    monkeypatch.setattr(s, "telegram_webhook_url", "https://bot.example.com/api/telegram/webhook")
    monkeypatch.setattr(s, "telegram_webhook_secret", SECRET)
    monkeypatch.setattr(s, "mini_app_url", MINI_APP)
    return s


async def test_menu_button_at_registration(session, webhook_settings, monkeypatch) -> None:
    from aiogram.types import WebhookInfo

    registered = WebhookInfo(
        url=webhook_settings.telegram_webhook_url,
        has_custom_certificate=False,
        pending_update_count=0,
        allowed_updates=["message"],
    )
    tg = RecordingSession()
    assert await ensure_webhook(create_bot(session=tg), create_dispatcher(), session)
    await session.commit()
    (menu,) = tg.calls("SetChatMenuButton")
    assert menu.chat_id is None  # the default for every chat
    assert (menu.menu_button.text, menu.menu_button.web_app.url) == ("បើកកម្មវិធី", MINI_APP)
    assert [c.command for c in tg.calls("SetMyCommands")[0].commands] == ["start", "lang"]
    # Same settings: nothing to do.
    tg = RecordingSession(responses={"GetWebhookInfo": registered})
    assert not await ensure_webhook(create_bot(session=tg), create_dispatcher(), session)
    assert tg.calls("SetChatMenuButton") == []
    # A new Mini App URL: registered again, the menu button refreshed.
    monkeypatch.setattr(webhook_settings, "mini_app_url", "https://new.example.com")
    tg = RecordingSession(responses={"GetWebhookInfo": registered})
    assert await ensure_webhook(create_bot(session=tg), create_dispatcher(), session)
    assert tg.calls("SetChatMenuButton")[0].menu_button.web_app.url == "https://new.example.com"


async def test_default_menu_button_without_https(session, webhook_settings, monkeypatch) -> None:
    monkeypatch.setattr(webhook_settings, "mini_app_url", "")
    tg = RecordingSession()
    await ensure_webhook(create_bot(session=tg), create_dispatcher(), session)
    (menu,) = tg.calls("SetChatMenuButton")
    assert menu.menu_button.type == "default"
