"""POST /api/telegram/webhook: secret check, dispatch into the aiogram handlers, error handling."""

import logging

import pytest
from sqlalchemy import select

from app.bot import handlers
from app.bot.runtime import TelegramRuntime, create_runtime
from app.bot.setup import create_bot, create_dispatcher
from app.config import Settings, get_settings
from app.main import app
from app.models import BotPref, Language, Role, User
from tests.conftest import TEST_BOT_TOKEN
from tests.telegram_fakes import RecordingSession, command_update

WEBHOOK = "http://test/api/telegram/webhook"
SECRET = "test_webhook-secret_123"
HEADERS = {"X-Telegram-Bot-Api-Secret-Token": SECRET}


@pytest.fixture
def tg() -> RecordingSession:
    return RecordingSession()


@pytest.fixture
def runtime(tg: RecordingSession):
    rt = TelegramRuntime(bot=create_bot(session=tg), dp=create_dispatcher(), secret=SECRET)
    app.state.telegram = rt
    yield rt
    app.state.telegram = None


@pytest.fixture
def mini_app_url(monkeypatch) -> str:
    url = "https://meanchey.example.com"
    monkeypatch.setattr(get_settings(), "mini_app_url", url)
    return url


# --- secret token -------------------------------------------------------------------------


@pytest.mark.parametrize(
    "headers",
    [{}, {"X-Telegram-Bot-Api-Secret-Token": "wrong"}, {"X-Telegram-Bot-Api-Secret-Token": ""}],
)
async def test_bad_or_missing_secret_is_rejected(client, runtime, tg, headers, caplog) -> None:
    fed: list = []
    runtime.dp.feed_update = lambda *a, **k: fed.append(a)  # type: ignore[method-assign]
    with caplog.at_level(logging.WARNING, logger="app.bot.webhook"):
        r = await client.post(WEBHOOK, json=command_update("/start"), headers=headers)
    assert r.status_code == 401
    assert fed == []
    assert tg.requests == []
    assert "rejected Telegram webhook call" in caplog.text
    assert SECRET not in caplog.text


# --- /start ---------------------------------------------------------------------------------


async def test_start_sends_webapp_button(client, runtime, tg, mini_app_url) -> None:
    r = await client.post(WEBHOOK, json=command_update("/start", tg_id=777), headers=HEADERS)
    assert r.status_code == 200
    (sent,) = tg.calls("SendMessage")
    assert sent.chat_id == 777
    assert "មាន់អាំងមានជ័យ" in sent.text  # Khmer by default
    button = sent.reply_markup.inline_keyboard[0][0]
    assert button.web_app.url == mini_app_url


@pytest.mark.parametrize("url", ["", "http://insecure.example.com"])
async def test_start_without_https_mini_app_url(client, runtime, tg, monkeypatch, url) -> None:
    monkeypatch.setattr(get_settings(), "mini_app_url", url)
    r = await client.post(WEBHOOK, json=command_update("/start"), headers=HEADERS)
    assert r.status_code == 200
    (sent,) = tg.calls("SendMessage")
    assert sent.reply_markup is None
    assert "កម្មវិធីមិនទាន់បានកំណត់" in sent.text  # "app not configured"


async def test_start_uses_linked_user_language(
    client, runtime, tg, session, make_user, mini_app_url
) -> None:
    user = await make_user(Role.STAFF, "linked_staff", telegram_user_id=888)
    user.language = Language.EN
    await session.commit()
    await client.post(WEBHOOK, json=command_update("/start", tg_id=888), headers=HEADERS)
    (sent,) = tg.calls("SendMessage")
    assert "Welcome to <b>Mean Chey Grilled Chicken</b>" in sent.text


# --- /lang ----------------------------------------------------------------------------------


async def test_lang_toggles_for_unlinked_user(client, runtime, tg, session, mini_app_url):
    await client.post(WEBHOOK, json=command_update("/lang", tg_id=555), headers=HEADERS)
    pref = await session.get(BotPref, 555)
    assert pref is not None and pref.language == Language.EN
    assert tg.calls("SendMessage")[-1].text.startswith("✅ Language switched to English")

    await client.post(
        WEBHOOK, json=command_update("/lang", tg_id=555, update_id=2), headers=HEADERS
    )
    await session.refresh(pref)
    assert pref.language == Language.KM


async def test_lang_toggles_for_linked_user(client, runtime, session, make_user, mini_app_url):
    user = await make_user(Role.STAFF, "linked_lang", telegram_user_id=999)
    assert user.language == Language.KM
    r = await client.post(WEBHOOK, json=command_update("/lang", tg_id=999), headers=HEADERS)
    assert r.status_code == 200
    lang = await session.scalar(select(User.language).where(User.id == user.id))
    assert lang == Language.EN
    assert (await session.get(BotPref, 999)).language == Language.EN


# --- errors ---------------------------------------------------------------------------------


async def test_handler_exception_still_returns_200(client, runtime, monkeypatch, caplog):
    async def boom(_: int) -> Language:
        raise RuntimeError("database exploded")

    monkeypatch.setattr(handlers, "get_language", boom)
    with caplog.at_level(logging.ERROR, logger="app.bot.webhook"):
        r = await client.post(WEBHOOK, json=command_update("/start"), headers=HEADERS)
    assert r.status_code == 200
    assert "error while handling Telegram update" in caplog.text
    assert "database exploded" in caplog.text


async def test_malformed_update_still_returns_200(client, runtime, caplog) -> None:
    with caplog.at_level(logging.ERROR, logger="app.bot.webhook"):
        r = await client.post(WEBHOOK, content=b"not json", headers=HEADERS)
    assert r.status_code == 200
    assert "error while handling Telegram update" in caplog.text


# --- modes ----------------------------------------------------------------------------------


async def test_endpoint_404_without_runtime(client) -> None:
    app.state.telegram = None
    r = await client.post(WEBHOOK, json=command_update("/start"), headers=HEADERS)
    assert r.status_code == 404


def _settings(**overrides) -> Settings:
    values = {
        "jwt_secret": "x" * 32,
        "telegram_bot_token": TEST_BOT_TOKEN,
        "telegram_webhook_url": "https://example.com/api/telegram/webhook",
        "telegram_webhook_secret": SECRET,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


@pytest.mark.parametrize(
    "overrides",
    [
        {"bot_mode": "polling"},
        {"bot_mode": "off"},
        {"bot_mode": "webhook", "telegram_bot_token": ""},
    ],
)
def test_no_runtime_in_polling_off_or_without_token(overrides) -> None:
    # No runtime → app.state.telegram stays None → the endpoint 404s (see test above).
    assert create_runtime(_settings(**overrides)) is None


async def test_runtime_in_webhook_mode() -> None:
    rt = create_runtime(_settings(bot_mode="webhook"))
    assert rt is not None and rt.secret == SECRET
    await rt.close()
