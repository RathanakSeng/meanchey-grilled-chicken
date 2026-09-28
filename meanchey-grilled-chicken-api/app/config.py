import re
from functools import lru_cache
from typing import Literal
from urllib.parse import urlsplit

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BotMode = Literal["webhook", "polling", "off"]

# Telegram only delivers webhooks over HTTPS to these ports.
TELEGRAM_WEBHOOK_PORTS = frozenset({443, 80, 88, 8443})
_WEBHOOK_SECRET_RE = re.compile(r"[A-Za-z0-9_-]{1,256}")


def validate_webhook_url(url: str) -> None:
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.hostname:
        raise ValueError("TELEGRAM_WEBHOOK_URL must be a full https:// URL")
    try:
        port = parts.port or 443
    except ValueError as e:
        raise ValueError("TELEGRAM_WEBHOOK_URL has an invalid port") from e
    if port not in TELEGRAM_WEBHOOK_PORTS:
        allowed = sorted(TELEGRAM_WEBHOOK_PORTS)
        raise ValueError(f"TELEGRAM_WEBHOOK_URL port must be one of {allowed} (got {port})")


def validate_webhook_secret(secret: str) -> None:
    if not _WEBHOOK_SECRET_RE.fullmatch(secret):
        raise ValueError(
            "TELEGRAM_WEBHOOK_SECRET must be 1-256 characters of A-Z, a-z, 0-9, _ or -"
        )


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    environment: str = "development"

    database_url: str = "postgresql+asyncpg://meanchey:meanchey@localhost:5432/meanchey"
    # Use a NullPool (no connection reuse). Handy for tests and one-off scripts.
    db_null_pool: bool = False

    jwt_secret: str
    jwt_algorithm: str = "HS256"
    access_token_ttl_minutes: int = 15
    refresh_token_ttl_days: int = 7

    superadmin_initial_password: str = "superadmin"

    login_max_attempts: int = 5
    login_lock_minutes: int = 15

    telegram_bot_token: str = ""
    telegram_init_data_max_age_seconds: int = 24 * 60 * 60
    mini_app_url: str = ""

    # How the bot receives updates: FastAPI webhook, separate polling process, or not at all.
    bot_mode: BotMode = "webhook"
    telegram_webhook_url: str = ""
    telegram_webhook_secret: str = ""
    telegram_webhook_auto_set: bool = True
    telegram_drop_pending_updates: bool = False

    # Comma-separated list of allowed browser origins.
    cors_origins: str = "http://localhost:5173"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def webhook_enabled(self) -> bool:
        """The API serves the Telegram webhook (webhook mode and a bot token is configured)."""
        return self.bot_mode == "webhook" and bool(self.telegram_bot_token)

    @model_validator(mode="after")
    def _check_webhook_settings(self) -> "Settings":
        # Fail fast at startup rather than silently never receiving updates.
        if self.webhook_enabled:
            validate_webhook_url(self.telegram_webhook_url)
            validate_webhook_secret(self.telegram_webhook_secret)
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
