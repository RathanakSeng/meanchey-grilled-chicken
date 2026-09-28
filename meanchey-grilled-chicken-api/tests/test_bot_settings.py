"""Webhook settings are validated at startup (only in webhook mode with a token)."""

import pytest
from pydantic import ValidationError

from app.config import Settings
from tests.conftest import TEST_BOT_TOKEN

GOOD_URL = "https://example.com/api/telegram/webhook"
GOOD_SECRET = "Abc_123-xyz"


def make(**overrides) -> Settings:
    values = {
        "jwt_secret": "x" * 32,
        "bot_mode": "webhook",
        "telegram_bot_token": TEST_BOT_TOKEN,
        "telegram_webhook_url": GOOD_URL,
        "telegram_webhook_secret": GOOD_SECRET,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


@pytest.mark.parametrize(
    "url",
    [
        GOOD_URL,
        "https://example.com:8443/api/telegram/webhook",
        "https://example.com:88/hook",
        "https://example.com:80/hook",
        "https://abcd-1-2-3-4.ngrok-free.app/api/telegram/webhook",
    ],
)
def test_valid_urls(url: str) -> None:
    assert make(telegram_webhook_url=url).telegram_webhook_url == url


@pytest.mark.parametrize(
    ("url", "message"),
    [
        ("http://example.com/api/telegram/webhook", "https://"),
        ("", "https://"),
        ("example.com/api/telegram/webhook", "https://"),
        ("https://example.com:8080/api/telegram/webhook", "port"),
        ("https://example.com:5173/api/telegram/webhook", "port"),
    ],
)
def test_invalid_urls(url: str, message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        make(telegram_webhook_url=url)


@pytest.mark.parametrize("secret", ["a", "A" * 256, "only-dashes_and_underscores_09"])
def test_valid_secrets(secret: str) -> None:
    make(telegram_webhook_secret=secret)


@pytest.mark.parametrize("secret", ["", "has space", "bad!char", "ក្រោយ", "A" * 257, "a/b"])
def test_invalid_secrets(secret: str) -> None:
    with pytest.raises(ValidationError, match="TELEGRAM_WEBHOOK_SECRET"):
        make(telegram_webhook_secret=secret)


@pytest.mark.parametrize(
    "overrides",
    [
        {"bot_mode": "polling"},
        {"bot_mode": "off"},
        {"bot_mode": "webhook", "telegram_bot_token": ""},
    ],
)
def test_not_validated_outside_webhook_mode(overrides) -> None:
    make(telegram_webhook_url="http://bad", telegram_webhook_secret="bad secret", **overrides)


def test_invalid_bot_mode() -> None:
    with pytest.raises(ValidationError):
        make(bot_mode="sometimes")
