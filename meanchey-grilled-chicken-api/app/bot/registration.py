"""Registering the Telegram webhook (setWebhook / deleteWebhook / getWebhookInfo).

Telegram's getWebhookInfo never returns the secret token, so we store a SHA-256 fingerprint of
what we last registered (URL, secret, allowed updates, drop-pending flag) in `app_settings`.
setWebhook is only called when Telegram's URL / allowed updates or that fingerprint differ.
"""

import hashlib
import json
import logging

from aiogram import Bot, Dispatcher
from aiogram.types import WebhookInfo
from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.setup import BOT_COMMANDS
from app.config import get_settings
from app.models import AppSetting, utcnow

log = logging.getLogger(__name__)

FINGERPRINT_KEY = "telegram.webhook.fingerprint"
TELEGRAM_TIMEOUT_SECONDS = 10


def webhook_fingerprint(
    url: str, secret: str, allowed_updates: list[str], drop_pending: bool
) -> str:
    payload = json.dumps(
        {"url": url, "secret": secret, "allowed": sorted(allowed_updates), "drop": drop_pending},
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


async def _store_fingerprint(session: AsyncSession, value: str) -> None:
    await session.execute(
        pg_insert(AppSetting)
        .values(key=FINGERPRINT_KEY, value=value)
        .on_conflict_do_update(
            index_elements=[AppSetting.key], set_={"value": value, "updated_at": utcnow()}
        )
    )


async def _stored_fingerprint(session: AsyncSession) -> str | None:
    row = await session.get(AppSetting, FINGERPRINT_KEY)
    return row.value if row else None


async def set_webhook(bot: Bot, dp: Dispatcher, session: AsyncSession) -> None:
    """Unconditionally register the webhook from settings. Raises on Telegram errors.

    Does not commit; the caller owns the transaction.
    """
    s = get_settings()
    if not s.telegram_webhook_url or not s.telegram_webhook_secret:
        raise RuntimeError("TELEGRAM_WEBHOOK_URL and TELEGRAM_WEBHOOK_SECRET must be set")
    allowed = sorted(dp.resolve_used_update_types())
    await bot.set_webhook(
        url=s.telegram_webhook_url,
        secret_token=s.telegram_webhook_secret,
        allowed_updates=allowed,
        drop_pending_updates=s.telegram_drop_pending_updates,
        request_timeout=TELEGRAM_TIMEOUT_SECONDS,
    )
    await bot.set_my_commands(BOT_COMMANDS, request_timeout=TELEGRAM_TIMEOUT_SECONDS)
    await _store_fingerprint(
        session,
        webhook_fingerprint(
            s.telegram_webhook_url,
            s.telegram_webhook_secret,
            allowed,
            s.telegram_drop_pending_updates,
        ),
    )
    log.info("Telegram webhook registered: %s (updates: %s)", s.telegram_webhook_url, allowed)


async def ensure_webhook(bot: Bot, dp: Dispatcher, session: AsyncSession) -> bool:
    """Register the webhook if it isn't already up to date. Never raises.

    Returns True if setWebhook was called. Does not commit.
    """
    s = get_settings()
    allowed = sorted(dp.resolve_used_update_types())
    expected = webhook_fingerprint(
        s.telegram_webhook_url,
        s.telegram_webhook_secret,
        allowed,
        s.telegram_drop_pending_updates,
    )
    try:
        info = await bot.get_webhook_info(request_timeout=TELEGRAM_TIMEOUT_SECONDS)
        up_to_date = (
            info.url == s.telegram_webhook_url
            and sorted(info.allowed_updates or []) == allowed
            and await _stored_fingerprint(session) == expected
        )
        if up_to_date:
            log.info("Telegram webhook already up to date: %s", info.url)
            return False
        await set_webhook(bot, dp, session)
        return True
    except Exception:
        # The API must still come up if Telegram is unreachable; retry on next start or via CLI.
        log.exception("could not register the Telegram webhook; continuing startup")
        return False


async def delete_webhook(bot: Bot, session: AsyncSession, drop_pending: bool = False) -> None:
    """Remove the webhook (e.g. before polling). Does not commit."""
    await bot.delete_webhook(
        drop_pending_updates=drop_pending, request_timeout=TELEGRAM_TIMEOUT_SECONDS
    )
    await session.execute(delete(AppSetting).where(AppSetting.key == FINGERPRINT_KEY))


async def webhook_info(bot: Bot) -> WebhookInfo:
    return await bot.get_webhook_info(request_timeout=TELEGRAM_TIMEOUT_SECONDS)
