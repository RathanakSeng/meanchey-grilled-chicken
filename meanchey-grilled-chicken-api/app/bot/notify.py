"""Send stored notifications to Telegram (after the action's commit).

`deliver(ids, runtime)` runs as a FastAPI background task: its own database session, one message
per notification in the recipient's language, and the outcome in `telegram_status`:

- `sent` (with `sent_at`), `failed` (+ `telegram_error`, logged; no retry loop:
  `python -m app.bot notifications resend-failed`),
- `not_linked`: the recipient has no Telegram account bound,
- `bot_off`: no token, `BOT_MODE=off`, or webhook mode without a runtime.

Webhook mode uses the API's own `Bot` (`app.state.telegram`); polling mode creates a short-lived
one (the poller runs in another process). Nothing here raises: an alert must never fail the step.
"""

import logging
import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from html import escape
from typing import Any

from aiogram import Bot
from aiogram.types import BufferedInputFile, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from sqlalchemy import select

from app.bot.i18n import t
from app.bot.runtime import TelegramRuntime
from app.bot.setup import create_bot
from app.config import get_settings
from app.db import SessionLocal
from app.models import Language, Notification, User, utcnow
from app.services.notification_service import (
    COMPLETED,
    ORDER_DELIVERED,
    ORDER_DELIVERING,
    ORDER_RETURN_PENDING,
    ORDER_RETURNS_REVIEWED,
    PROCESSING_FINISHED,
)

log = logging.getLogger(__name__)

# Replaced in tests to inject a recording session.
bot_factory: Callable[[], Bot] = create_bot

ERROR_MAX_LENGTH = 500
DOCUMENT_TIMEOUT_SECONDS = 30


def mini_app_link(path: str) -> str | None:
    """MINI_APP_URL + an app path, or None when the Mini App URL isn't HTTPS."""
    base = get_settings().mini_app_url
    if not base.startswith("https://"):
        return None
    return base.rstrip("/") + path


def _items_text(lang: Language, items: list[dict[str, Any]] | None) -> str:
    """ "3 × 4-Piece Packs, 1.200 kg Liver (packed)" in `lang` (names escaped)."""
    parts = []
    for item in items or []:
        name = escape(str(item.get("name_km" if lang == Language.KM else "name_en", "")))
        if item.get("count") is not None:
            parts.append(t(lang, "order_item_count", name=name, count=item["count"]))
        else:
            parts.append(t(lang, "order_item_kg", name=name, kg=item.get("kg")))
    return ", ".join(parts) if parts else t(lang, "order_nothing")


def _order_message(row: Notification, lang: Language) -> str:
    p: dict[str, Any] = row.payload
    code = escape(str(p.get("code", "")))
    customer = escape(str(p.get("customer", "")))
    if row.type == ORDER_DELIVERING:
        return t(
            lang,
            "order_delivering",
            code=code,
            customer=customer,
            white=p.get("white", 0),
            black=p.get("black", 0),
        )
    if row.type == ORDER_DELIVERED:
        return t(lang, "order_delivered", code=code, customer=customer)
    if row.type == ORDER_RETURN_PENDING:
        return t(
            lang,
            "order_return_pending",
            code=code,
            customer=customer,
            summary=_items_text(lang, p.get("returned")),
            reason=escape(str(p.get("reason") or "")),
        )
    outcome = (
        "order_fully_returned" if p.get("outcome") == "fully_returned" else "order_partly_returned"
    )
    return t(
        lang,
        "order_returns_reviewed",
        code=code,
        outcome=t(lang, outcome),
        to_stock=_items_text(lang, p.get("to_stock")),
        to_wasted=_items_text(lang, p.get("to_wasted")),
    )


ORDER_TYPES = (ORDER_DELIVERING, ORDER_DELIVERED, ORDER_RETURN_PENDING, ORDER_RETURNS_REVIEWED)


def message_for(row: Notification, lang: Language) -> tuple[str, InlineKeyboardMarkup | None]:
    """The alert text (HTML) and its Mini App button, in `lang`."""
    p: dict[str, Any] = row.payload
    again = t(lang, "again") if p.get("repeat") else ""
    code = escape(str(p.get("code", "")))
    if row.type in ORDER_TYPES:
        text = _order_message(row, lang)
        button, path = "open_order", f"/workstation/orders/{row.entity_id}"
    elif row.type == PROCESSING_FINISHED:
        text = t(
            lang,
            "processing_finished",
            code=code,
            again=again,
            quantity=p.get("quantity"),
            wings=p.get("wings"),
            thighs=p.get("thighs"),
        )
        button, path = "open_plan", f"/workstation/production-plans/{row.entity_id}"
    elif row.type == COMPLETED and p.get("matches"):
        text = t(
            lang,
            "completed_as_planned",
            code=code,
            again=again,
            big=p.get("actual_big"),
            small=p.get("actual_small"),
        )
        button, path = "open_batch", f"/workstation/production/{row.entity_id}?step=3"
    else:
        text = t(
            lang,
            "completed_differs",
            code=code,
            again=again,
            pb=p.get("planned_big"),
            ps=p.get("planned_small"),
            ab=p.get("actual_big"),
            as_=p.get("actual_small"),
            comment=escape(p.get("comment") or ""),
        )
        button, path = "open_batch", f"/workstation/production/{row.entity_id}?step=3"
    url = mini_app_link(path)
    keyboard = None
    if url:
        open_button = InlineKeyboardButton(text=t(lang, button), web_app=WebAppInfo(url=url))
        keyboard = InlineKeyboardMarkup(inline_keyboard=[[open_button]])
    return text, keyboard


async def _send_all(ids: list[uuid.UUID], bot: Bot | None) -> dict[str, int]:
    counts: dict[str, int] = {}
    async with SessionLocal() as session:
        rows = list(
            await session.scalars(
                select(Notification).where(Notification.id.in_(ids)).order_by(Notification.id)
            )
        )
        users = {
            u.id: u
            for u in await session.scalars(
                select(User).where(User.id.in_({r.user_id for r in rows}))
            )
        }
        for row in rows:
            user = users.get(row.user_id)
            if bot is None:
                row.telegram_status = "bot_off"
            elif user is None or user.telegram_user_id is None:
                row.telegram_status = "not_linked"
            else:
                text, keyboard = message_for(row, user.language)
                try:
                    await bot.send_message(user.telegram_user_id, text, reply_markup=keyboard)
                except Exception as e:  # blocked bot, network, bad request: logged, not retried
                    log.warning("Telegram alert %s to user %s failed: %s", row.id, user.id, e)
                    row.telegram_status = "failed"
                    row.telegram_error = str(e)[:ERROR_MAX_LENGTH]
                else:
                    row.telegram_status = "sent"
                    row.telegram_error = None
                    row.sent_at = utcnow()
            counts[row.telegram_status] = counts.get(row.telegram_status, 0) + 1
        await session.commit()
    return counts


@asynccontextmanager
async def api_bot(runtime: TelegramRuntime | None) -> AsyncIterator[Bot | None]:
    """The bot the API sends with: the runtime's in webhook mode, a short-lived one in polling
    mode (the poller is another process), None without a token / `BOT_MODE=off` / runtime."""
    settings = get_settings()
    if settings.telegram_bot_token and settings.bot_mode == "webhook" and runtime is not None:
        yield runtime.bot
    elif settings.telegram_bot_token and settings.bot_mode == "polling":
        bot = bot_factory()
        try:
            yield bot
        finally:
            await bot.session.close()
    else:
        yield None


async def deliver(ids: list[uuid.UUID], runtime: TelegramRuntime | None) -> None:
    """Background task after the commit that created `ids`. Never raises."""
    if not ids:
        return
    try:
        async with api_bot(runtime) as bot:
            await _send_all(ids, bot)
    except Exception:
        log.exception("Delivering notifications %s failed", ids)


async def send_document(
    bot: Bot, user: User, data: bytes, filename: str, code: str, customer: str
) -> None:
    """Send a PDF to `user`'s linked chat, captioned in their language. Raises on failure."""
    assert user.telegram_user_id is not None
    caption = t(user.language, "document_caption", code=escape(code), customer=escape(customer))
    await bot.send_document(
        user.telegram_user_id,
        BufferedInputFile(data, filename=filename),
        caption=caption,
        request_timeout=DOCUMENT_TIMEOUT_SECONDS,
    )


_bot_username: str | None = None


async def bot_username(runtime: TelegramRuntime | None) -> str | None:
    """The bot's @username (from getMe, cached per process); None without a token."""
    global _bot_username
    if _bot_username is None:
        if not get_settings().telegram_bot_token:
            return None
        if runtime is not None:
            me = await runtime.bot.get_me()
        else:
            bot = bot_factory()
            try:
                me = await bot.get_me()
            finally:
                await bot.session.close()
        _bot_username = me.username
    return _bot_username


async def resend_failed() -> dict[str, int]:
    """Retry every `failed` notification once, with a short-lived bot (CLI)."""
    async with SessionLocal() as session:
        ids = list(
            await session.scalars(
                select(Notification.id).where(Notification.telegram_status == "failed")
            )
        )
    if not ids:
        return {}
    bot = bot_factory()
    try:
        return await _send_all(ids, bot)
    finally:
        await bot.session.close()
