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
from datetime import date
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
from app.models import Language, Notification, Role, User, utcnow
from app.models.order import BOX_COLORS
from app.services.notification_service import (
    COMPLETED,
    HOLIDAY_OFF,
    HOLIDAY_WORK,
    INVENTORY_CLEARED,
    ORDER_DELIVERED,
    ORDER_DELIVERING,
    ORDER_RETURN_PENDING,
    ORDER_RETURNS_REVIEWED,
    PREPARATION_FINISHED,
    PROCESSING_FINISHED,
    REQUEST_APPROVED,
    REQUEST_REJECTED,
    REQUEST_REMINDER,
    REQUEST_SUBMITTED,
    SCHEDULE_CHANGED,
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


def _boxes_text(lang: Language, payload: dict[str, Any]) -> str:
    """ "2 white boxes, 1 plastic bag": containers without boxes left out (alerts from before the
    bags only carry white / black)."""
    parts = []
    for color in BOX_COLORS:
        n = int(payload.get(color) or 0)
        if n:
            # English plural: boxes, bags.
            s = "" if n == 1 else "es" if color in ("white", "black") else "s"
            parts.append(t(lang, f"boxes_{color}", n=n, s=s))
    return ", ".join(parts) if parts else t(lang, "order_nothing")


def customer_text(lang: Language, name: str | None, phone: str | None) -> str:
    """The order's customer, escaped: the name, or "Direct order · 012 345 678" without one."""
    if name:
        return escape(name)
    return t(lang, "direct_order", phone=escape(phone or "—"))


def _order_message(row: Notification, lang: Language) -> str:
    p: dict[str, Any] = row.payload
    code = escape(str(p.get("code", "")))
    customer = customer_text(lang, p.get("customer"), p.get("customer_phone"))
    if row.type == ORDER_DELIVERING:
        return t(
            lang,
            "order_delivering",
            code=code,
            customer=customer,
            boxes=_boxes_text(lang, p),
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


def preparation_summary(lang: Language, p: dict[str, Any]) -> str:
    """ "40 satay sachets (2-piece), 25 (4-piece) | Skewer 2.000 kg, String 0.500 kg" in `lang`
    (names escaped)."""
    groups = []
    sachets = [(size, p.get(f"sachets_{size}")) for size in (2, 4)]
    sachet_parts = [
        t(lang, "prep_sachets_first" if not i else "prep_sachets_more", count=n, size=size)
        for i, (size, n) in enumerate((s, n) for s, n in sachets if n)
    ]
    if sachet_parts:
        groups.append(", ".join(sachet_parts))
    material_parts = []
    for m in p.get("materials") or []:
        name = escape(str(m.get("name_km" if lang == Language.KM else "name_en", "")))
        unit = (
            t(lang, f"unit_{m.get('unit')}") if m.get("unit") in ("kg", "g", "m2", "count") else ""
        )
        material_parts.append(f"{name} {m.get('quantity')}{unit}")
    if material_parts:
        groups.append(", ".join(material_parts))
    return " | ".join(groups) if groups else t(lang, "order_nothing")


MONTHS = {
    Language.EN: [
        "January",
        "February",
        "March",
        "April",
        "May",
        "June",
        "July",
        "August",
        "September",
        "October",
        "November",
        "December",
    ],
    Language.KM: [
        "មករា",
        "កុម្ភៈ",
        "មីនា",
        "មេសា",
        "ឧសភា",
        "មិថុនា",
        "កក្កដា",
        "សីហា",
        "កញ្ញា",
        "តុលា",
        "វិច្ឆិកា",
        "ធ្នូ",
    ],
}
REQUEST_TYPES = (REQUEST_SUBMITTED, REQUEST_APPROVED, REQUEST_REJECTED, REQUEST_REMINDER)
SCHEDULE_TYPES = (SCHEDULE_CHANGED, HOLIDAY_WORK, HOLIDAY_OFF)
WEEKDAYS = {
    Language.EN: ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
    Language.KM: ["ច័ន្ទ", "អង្គារ", "ពុធ", "ព្រហស្បតិ៍", "សុក្រ", "សៅរ៍", "អាទិត្យ"],
}


def weekdays_text(lang: Language, days: list[int]) -> str:
    """ "Every day", "Mon–Sat" (a run of 3 or more), else "Mon, Wed, Fri"."""
    days = sorted(set(days))
    if len(days) == 7:
        return t(lang, "every_day")
    names = WEEKDAYS[lang]
    parts: list[str] = []
    run: list[int] = []
    for d in [*days, 0]:
        if run and d == run[-1] + 1:
            run.append(d)
            continue
        if len(run) >= 3:
            parts.append(f"{names[run[0] - 1]}–{names[run[-1] - 1]}")
        else:
            parts += [names[x - 1] for x in run]
        run = [d]
    return ", ".join(parts)


def shifts_text(lang: Language, shifts: list[dict[str, Any]]) -> str:
    """ "Morning 07:30–12:00, Afternoon 13:00–15:00"."""
    return ", ".join(
        f"{t(lang, f'shift_{s["code"]}_short')} {s['start_time']}–{s['end_time']}" for s in shifts
    )


def day_text(lang: Language, iso: str) -> str:
    d = date.fromisoformat(iso)
    if lang == Language.KM:
        return f"{d.day} {MONTHS[lang][d.month - 1]} {d.year}"
    return f"{WEEKDAYS[lang][d.isoweekday() - 1]} {d.day} {MONTHS[lang][d.month - 1][:3]} {d.year}"


def _schedule_message(row: Notification, lang: Language) -> str:
    p: dict[str, Any] = row.payload
    when = day_text(lang, p.get("date") or p.get("effective_from") or "2000-01-01")
    if row.type == SCHEDULE_CHANGED:
        return t(
            lang,
            "schedule_changed",
            date=when,
            weekdays=weekdays_text(lang, p.get("weekdays") or []),
            shifts=shifts_text(lang, p.get("shifts") or []),
        )
    holiday = escape(str(p.get("holiday_km" if lang == Language.KM else "holiday") or ""))
    if row.type == HOLIDAY_WORK:
        shifts = shifts_text(lang, p.get("shifts") or [])
        return t(lang, "holiday_work", holiday=holiday, date=when, shifts=shifts)
    return t(lang, "holiday_off", holiday=holiday, date=when)


def duration_text(lang: Language, minutes: int) -> str:
    """ "6 h 45", "2 h", "45 min" (km: ម៉ោង / នាទី)."""
    h, m = divmod(max(0, int(minutes)), 60)
    if h and m:
        return t(lang, "duration_hm", h=h, m=m)
    return t(lang, "duration_h", h=h) if h else t(lang, "duration_m", m=m)


def month_text(lang: Language, year: int, month: int) -> str:
    return f"{MONTHS[lang][month - 1]} {year}"


def split_text(lang: Language, salary_cut: int, unpaid_work: int) -> str:
    parts = []
    if salary_cut:
        parts.append(t(lang, "request_cut", duration=duration_text(lang, salary_cut)))
    if unpaid_work:
        parts.append(t(lang, "request_work", duration=duration_text(lang, unpaid_work)))
    return ", ".join(parts)


def _request_message(row: Notification, lang: Language) -> tuple[str, str, str]:
    """(text, button label key, path) of an attendance request alert."""
    p: dict[str, Any] = row.payload
    month = month_text(lang, int(p.get("year", 1)), int(p.get("month", 1)))
    split = split_text(lang, p.get("salary_cut_minutes", 0), p.get("unpaid_work_minutes", 0))
    path = f"/attendance/requests?request={row.entity_id}"
    if row.type == REQUEST_SUBMITTED:
        text = t(
            lang,
            "request_submitted",
            name=escape(str(p.get("name", ""))),
            month=month,
            missing=duration_text(lang, p.get("missing_minutes", 0)),
            split=split,
        )
        return text, "open_request", path
    if row.type == REQUEST_APPROVED:
        changes = ""
        if p.get("with_changes"):
            comment = escape(p.get("comment") or "")
            changes = t(
                lang, "request_approved_changes", comment=f": “{comment}”" if comment else ""
            )
        return (
            t(lang, "request_approved", month=month, split=split, changes=changes),
            "open_request",
            path,
        )
    if row.type == REQUEST_REJECTED:
        return (
            t(lang, "request_rejected", month=month, reason=escape(str(p.get("reason") or ""))),
            "open_request",
            path,
        )
    day, mon = p.get("deadline_day", 7), MONTHS[lang][int(p.get("deadline_month", 1)) - 1]
    text = t(
        lang,
        "request_reminder",
        month=month_text(lang, int(p.get("year", 1)), int(p.get("month", 1))),
        missing=duration_text(lang, p.get("missing_minutes", 0)),
        deadline=f"{day} {mon}",
    )
    return text, "create_request", "/attendance/requests"


def clear_message(lang: Language, p: dict[str, Any], actor_name: str | None) -> str:
    """ "🧹 Dara cleared stock CL-…: 4-Piece Packs 20, Liver (processed) 1.500 kg — “…”." plus
    what the acknowledged impacts affect (names escaped)."""
    name_key = "name_km" if lang == Language.KM else "name_en"
    items = ", ".join(
        f"{escape(str(i.get(name_key, '')))} {i.get('quantity')}"
        + (t(lang, f"unit_{i.get('unit')}") if i.get("unit") in ("kg", "g", "m2", "count") else "")
        for i in p.get("items") or []
    )
    text = t(
        lang,
        "inventory_cleared",
        name=escape(actor_name or t(lang, "system")),
        code=escape(str(p.get("code", ""))),
        items=items,
        reason=escape(str(p.get("reason") or "")),
    )
    impacts = p.get("impacts") or {}
    parts = [
        t(lang, f"clear_affects_{kind}" + ("_one" if impacts[kind] == 1 else ""), n=impacts[kind])
        for kind in ("order", "production", "plan", "preparation", "reopen")
        if impacts.get(kind)
    ]
    if parts:
        text += " " + t(lang, "clear_affects", list=t(lang, "list_sep").join(parts))
    return text


def message_for(
    row: Notification, lang: Language, actor_name: str | None = None
) -> tuple[str, InlineKeyboardMarkup | None]:
    """The alert text (HTML) and its Mini App button, in `lang`. `actor_name`: who acted, for
    alerts that name them (None: "System")."""
    p: dict[str, Any] = row.payload
    again = t(lang, "again") if p.get("repeat") else ""
    code = escape(str(p.get("code", "")))
    if row.type == INVENTORY_CLEARED:
        text = clear_message(lang, p, actor_name)
        button, path = "open_clear", f"/workstation/inventory/clears/{row.entity_id}"
    elif row.type in REQUEST_TYPES:
        text, button, path = _request_message(row, lang)
    elif row.type in SCHEDULE_TYPES:
        text, button, path = _schedule_message(row, lang), "open_attendance", "/attendance/me"
    elif row.type in ORDER_TYPES:
        text = _order_message(row, lang)
        button, path = "open_order", f"/workstation/orders/{row.entity_id}"
    elif row.type == PREPARATION_FINISHED:
        text = t(
            lang,
            "preparation_finished",
            code=code,
            again=again,
            summary=preparation_summary(lang, p),
        )
        button, path = "open_preparation", f"/workstation/preparations/{row.entity_id}"
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
        actor_ids = {
            uuid.UUID(r.payload["actor_id"])
            for r in rows
            if r.type == INVENTORY_CLEARED and r.payload.get("actor_id")
        }
        actors = (
            {u.id: u for u in await session.scalars(select(User).where(User.id.in_(actor_ids)))}
            if actor_ids
            else {}
        )
        for row in rows:
            user = users.get(row.user_id)
            if bot is None:
                row.telegram_status = "bot_off"
            elif user is None or user.telegram_user_id is None:
                row.telegram_status = "not_linked"
            else:
                actor = (
                    actors.get(uuid.UUID(row.payload["actor_id"]))
                    if row.type == (INVENTORY_CLEARED) and row.payload.get("actor_id")
                    else None
                )
                # The superadmin reads as "System" to everyone else (redaction, like the bell).
                hidden = actor is not None and actor.role == Role.SUPERADMIN != user.role
                actor_name = actor.full_name if actor is not None and not hidden else None
                text, keyboard = message_for(row, user.language, actor_name)
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
    bot: Bot,
    user: User,
    data: bytes,
    filename: str,
    code: str,
    customer: str | None,
    phone: str | None,
) -> None:
    """Send a PDF to `user`'s linked chat, captioned in their language. Raises on failure.

    `customer` / `phone`: the order's snapshot (no name for a direct order)."""
    assert user.telegram_user_id is not None
    caption = t(
        user.language,
        "document_caption",
        code=escape(code),
        customer=customer_text(user.language, customer, phone),
    )
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
