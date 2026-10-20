"""Attendance messages on Telegram: check-in / check-out confirmations and reminders.

Both are sent **after the commit** that caused them, in the user's language, with an inline
`web_app` button opening the check screen (`/attendance/check`, which decides the action). The
bot used is `notify.api_bot` (the runtime's in webhook mode, a short-lived one in polling mode).
Nothing here raises: a message must never fail a check-in or a scheduler tick.
"""

import logging
import uuid
from datetime import datetime

from sqlalchemy import select

from app.attendance import clock
from app.attendance.windows import is_open, shown_until
from app.bot.handlers import check_keyboard
from app.bot.i18n import TEXTS, t
from app.bot.notify import ERROR_MAX_LENGTH, api_bot
from app.bot.runtime import TelegramRuntime
from app.config import get_settings
from app.db import SessionLocal
from app.models import AttendanceRecord, AttendanceReminder, Language, User, utcnow

log = logging.getLogger(__name__)


def shift_name(lang: Language, code: str, *, short: bool = False) -> str:
    key = f"shift_{code}_short" if short else f"shift_{code}"
    return t(lang, key) if key in TEXTS else code


def clock_time(value: datetime) -> str:
    """ "07:12" in the business time zone."""
    return value.astimezone(get_settings().business_tz).strftime("%H:%M")


def confirmation_text(lang: Language, action: str, record: AttendanceRecord) -> str:
    shift = shift_name(lang, record.shift_code)
    if action == "check_in":
        assert record.check_in_at is not None
        text = t(lang, "checked_in", shift=shift, time=clock_time(record.check_in_at))
        if record.late_minutes:
            text += t(lang, "checked_in_late", minutes=record.late_minutes)
        elif record.early_minutes:
            text += t(lang, "checked_in_early", minutes=record.early_minutes)
        return text
    assert record.check_out_at is not None
    text = t(lang, "checked_out", shift=shift, time=clock_time(record.check_out_at))
    if record.overtime_minutes:
        text += t(lang, "checked_out_overtime", minutes=record.overtime_minutes)
    return text


async def send_confirmation(
    record_id: uuid.UUID, action: str, runtime: TelegramRuntime | None
) -> None:
    """Background task after a successful check-in / check-out. Never raises."""
    try:
        async with SessionLocal() as session:
            record = await session.get(AttendanceRecord, record_id)
            user = await session.get(User, record.user_id) if record else None
        if record is None or user is None or user.telegram_user_id is None:
            return
        async with api_bot(runtime) as bot:
            if bot is None:
                return
            await bot.send_message(
                user.telegram_user_id,
                confirmation_text(user.language, action, record),
                reply_markup=check_keyboard(user.language, "button_attendance"),
            )
    except Exception:
        log.exception("Attendance confirmation for record %s failed", record_id)


def reminder_text(lang: Language, kind: str, shift_code: str, closes_at: datetime) -> str:
    end = clock_time(shown_until(closes_at))
    return t(
        lang,
        f"reminder_{kind}",
        shift=shift_name(lang, shift_code),
        shift_short=shift_name(lang, shift_code, short=True),
        end=end,
    )


async def send_reminders(
    ids: list[uuid.UUID], runtime: TelegramRuntime | None, now: datetime | None = None
) -> dict[str, int]:
    """Send claimed reminders (status `sending`) and record each outcome. A reminder that is no
    longer needed (already checked in / out) or whose window closed meanwhile is `skipped`."""
    counts: dict[str, int] = {}
    if not ids:
        return counts
    now = now or clock.now()
    try:
        async with api_bot(runtime) as bot, SessionLocal() as session:
            rows = list(
                await session.scalars(
                    select(AttendanceReminder)
                    .where(AttendanceReminder.id.in_(ids))
                    .order_by(AttendanceReminder.created_at, AttendanceReminder.id)
                )
            )
            users = {
                u.id: u
                for u in await session.scalars(
                    select(User).where(User.id.in_({r.user_id for r in rows}))
                )
            }
            records = {
                (r.user_id, r.work_date, r.shift_code): r
                for r in await session.scalars(
                    select(AttendanceRecord).where(
                        AttendanceRecord.user_id.in_(users),
                        AttendanceRecord.work_date.in_({r.work_date for r in rows}),
                    )
                )
            }
            for row in rows:
                user = users.get(row.user_id)
                record = records.get((row.user_id, row.work_date, row.shift_code))
                needed = record is None if row.kind == "check_in" else is_open(record)
                if not needed or now >= row.window_closes_at:
                    row.telegram_status = "skipped"
                elif bot is None:
                    row.telegram_status = "bot_off"
                elif user is None or user.telegram_user_id is None or not user.is_active:
                    row.telegram_status = "not_linked"
                else:
                    button = "button_check_in" if row.kind == "check_in" else "button_check_out"
                    try:
                        await bot.send_message(
                            user.telegram_user_id,
                            reminder_text(
                                user.language, row.kind, row.shift_code, row.window_closes_at
                            ),
                            reply_markup=check_keyboard(user.language, button),
                        )
                    except Exception as e:  # blocked bot, network: logged, not retried
                        log.warning("Attendance reminder %s to %s failed: %s", row.id, user.id, e)
                        row.telegram_status = "failed"
                        row.telegram_error = str(e)[:ERROR_MAX_LENGTH]
                    else:
                        row.telegram_status = "sent"
                        row.sent_at = utcnow()
                counts[row.telegram_status] = counts.get(row.telegram_status, 0) + 1
            await session.commit()
    except Exception:
        log.exception("Sending attendance reminders %s failed", ids)
    return counts
