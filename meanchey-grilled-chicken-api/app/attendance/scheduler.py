"""The attendance scheduler: absent records, "forgot check-out" and reminders, once a minute.

A background task in the API process (`run_forever`, started by the lifespan unless
`ATTENDANCE_SCHEDULER_ENABLED=false`). Each tick (`run_tick`) is one transaction guarded by
`pg_try_advisory_xact_lock`, so with several workers or replicas exactly one does the work and
the others skip that minute. Every step is idempotent and keyed on "now ≥ the cutoff" for
**today**, so a tick after a restart catches up on what was missed. Everything is evaluated
**per workplace** (with its schedule version for the date) for the employees assigned to it; an
employee without an active workplace counts at the default one. **Days off** (a weekday the
schedule doesn't track, or a holiday) are skipped entirely: no absents, no forgot check-out, no
reminders (waiting ones are skipped).

**Personal schedules** (employee overrides, holiday exceptions; `Days.resolve`): employees whose
day may differ from their workplace's are taken out of the workplace's group and handled in
groups of identical days (same shifts and times), so reminders, absents and forgot check-out
follow each person's own times and only the shifts they are expected to work:

- **Absent:** from a shift's check-in cutoff (start + absent_after), an `absent` record
  (`source = auto`) for every tracked employee without one, who existed before the cutoff.
- **Forgot check-out:** from the check-out window's close, open records get
  `checkout_status = forgot_checkout`.
- **Reminders** (when the workplace has them on), only while their window is open (no late
  catch-up spam after downtime): check-in to tracked, linked employees without a record;
  check-out to those checked in and not out. A row in `attendance_reminders` (unique per user /
  day / shift / kind) makes each one go out once; rows are claimed (`pending → sending`) inside
  the tick, then sent after the commit.

`rerun` replays passed cutoffs (absent, forgot check-out; never reminders) for given past dates,
when a holiday is removed or shortened or a day becomes tracked again.
"""

import asyncio
import logging
import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from sqlalchemy import ColumnElement, and_, func, or_, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.attendance import clock
from app.attendance import windows as win
from app.attendance.days import Days, load_days
from app.attendance.month_lock import month_locked_sql
from app.attendance.telegram import send_reminders
from app.attendance.tracking import tracked_on_sql
from app.bot.runtime import TelegramRuntime
from app.config import get_settings
from app.db import SessionLocal
from app.models import AttendanceRecord, AttendanceReminder, AttendanceWorkplace, User, utcnow

log = logging.getLogger(__name__)

SCHEDULER_LOCK_KEY = 815_002
TICK_SECONDS = 60


@dataclass
class TickResult:
    absent: int = 0
    forgot_checkout: int = 0
    reminders: list[uuid.UUID] = field(default_factory=list)
    skipped: int = 0
    skipped_locked: int = 0  # absents not recreated: a pending / approved request locks the month
    sent: dict[str, int] = field(default_factory=dict)


def _tracked(day: date, *extra: ColumnElement[bool]) -> ColumnElement[bool]:
    """Employees tracked on `day`: staff / supervisors, active, started, not switched off."""
    return tracked_on_sql(day, *extra)


def _assigned(workplace: AttendanceWorkplace, active_ids: list[uuid.UUID]) -> ColumnElement[bool]:
    """Employees who check in at this workplace (the default one also takes those whose
    workplace is missing or archived)."""
    if workplace.is_default:
        return or_(
            User.workplace_id.is_(None),
            User.workplace_id.not_in(active_ids),
            User.workplace_id == workplace.id,
        )
    return User.workplace_id == workplace.id


async def _mark_absent(
    session: AsyncSession,
    w: win.ShiftWindows,
    workplace_id: uuid.UUID,
    at: ColumnElement[bool],
    result: TickResult,
) -> int:
    has_record = (
        select(AttendanceRecord.id)
        .where(
            AttendanceRecord.user_id == User.id,
            AttendanceRecord.work_date == w.work_date,
            AttendanceRecord.shift_code == w.code,
        )
        .exists()
    )
    # Only people who were employees when the check-in closed.
    due = _tracked(w.work_date, at, User.created_at < w.check_in_closes, ~has_record)
    locked = month_locked_sql(User.id, w.work_date)
    user_ids = list(await session.scalars(select(User.id).where(due, ~locked)))
    result.skipped_locked += (
        await session.scalar(select(func.count(User.id)).where(due, locked)) or 0
    )
    if not user_ids:
        return 0
    now = utcnow()
    result = await session.execute(
        pg_insert(AttendanceRecord)
        .values(
            [
                {
                    "id": uuid.uuid4(),
                    "user_id": user_id,
                    "work_date": w.work_date,
                    "shift_code": w.code,
                    "workplace_id": workplace_id,
                    "scheduled_start": w.start,
                    "scheduled_end": w.end,
                    "status": "absent",
                    "late_minutes": 0,
                    "source": "auto",
                    "created_at": now,
                    "updated_at": now,
                }
                for user_id in user_ids
            ]
        )
        .on_conflict_do_nothing(constraint="uq_attendance_records_shift")
        .returning(AttendanceRecord.id)
    )
    return len(result.all())


async def _mark_forgot(
    session: AsyncSession, w: win.ShiftWindows, records: ColumnElement[bool]
) -> int:
    """Open records of this shift among `records` (a workplace's: records keep the workplace
    they were made at; or a group of employees with their own times)."""
    result = await session.execute(
        update(AttendanceRecord)
        .where(
            records,
            AttendanceRecord.work_date == w.work_date,
            AttendanceRecord.shift_code == w.code,
            AttendanceRecord.status != "absent",
            AttendanceRecord.checkout_status.is_(None),
            # Not for someone switched off since: their record is kept as it is.
            AttendanceRecord.user_id.in_(select(User.id).where(_tracked(w.work_date))),
        )
        .values(checkout_status="forgot_checkout", updated_at=utcnow())
        .returning(AttendanceRecord.id)
    )
    return len(result.all())


async def _queue_reminders(
    session: AsyncSession,
    w: win.ShiftWindows,
    kind: str,
    now: datetime,
    at: ColumnElement[bool],
) -> None:
    record = and_(
        AttendanceRecord.user_id == User.id,
        AttendanceRecord.work_date == w.work_date,
        AttendanceRecord.shift_code == w.code,
    )
    linked = User.telegram_user_id.is_not(None)
    if kind == "check_in":
        condition = _tracked(
            w.work_date, at, linked, ~select(AttendanceRecord.id).where(record).exists()
        )
        closes = w.check_in_closes
    else:
        open_record = (
            select(AttendanceRecord.id)
            .where(
                record,
                AttendanceRecord.status != "absent",
                AttendanceRecord.checkout_status.is_(None),
            )
            .exists()
        )
        condition = _tracked(w.work_date, at, linked, open_record)
        closes = w.check_out_closes
    user_ids = list(await session.scalars(select(User.id).where(condition)))
    if not user_ids:
        return
    await session.execute(
        pg_insert(AttendanceReminder)
        .values(
            [
                {
                    "id": uuid.uuid4(),
                    "user_id": user_id,
                    "work_date": w.work_date,
                    "shift_code": w.code,
                    "kind": kind,
                    "window_closes_at": closes,
                    "created_at": now,
                }
                for user_id in user_ids
            ]
        )
        .on_conflict_do_nothing(constraint="uq_attendance_reminders_once")
    )


async def _active_workplaces(session: AsyncSession) -> list[AttendanceWorkplace]:
    return list(
        await session.scalars(
            select(AttendanceWorkplace)
            .where(AttendanceWorkplace.is_active)
            .order_by(AttendanceWorkplace.is_default.desc(), AttendanceWorkplace.id)
        )
    )


@dataclass
class _Group:
    """Employees evaluated together at one workplace on one date."""

    workplace: AttendanceWorkplace
    at: ColumnElement[bool]  # who (on `User`)
    records: ColumnElement[bool]  # their records (on `AttendanceRecord`), for forgot check-out
    windows: list[win.ShiftWindows]
    off: bool  # a day off for all of them
    reminders: bool


async def _groups(
    session: AsyncSession, days: Days, workplaces: list[AttendanceWorkplace], day: date
) -> list[_Group]:
    """Per workplace: everyone following its schedule as one group, then the employees with a
    personal day (override or holiday exception), grouped by identical windows."""
    active_ids = [w.id for w in workplaces]
    default = next((w for w in workplaces if w.is_default), None)
    personal = days.personal_ids(day)
    by_key: dict[tuple, list[uuid.UUID]] = {}
    if personal:
        rows = await session.execute(
            select(User.id, User.workplace_id).where(User.id.in_(personal))
        )
        for user_id, workplace_id in rows:
            wid = workplace_id if workplace_id in active_ids else (default.id if default else None)
            if wid is None:
                continue
            r = days.resolve(wid, day, user_id)
            key = (wid, r.day_off is not None, tuple((d.code, d.start, d.end) for d in r.defs))
            by_key.setdefault(key, []).append(user_id)
    groups: list[_Group] = []
    for workplace in workplaces:
        resolved = days.resolve(workplace.id, day)
        reminders = resolved.rules.reminders_enabled
        at = _assigned(workplace, active_ids)
        records = AttendanceRecord.workplace_id == workplace.id
        if personal:
            at = and_(at, User.id.not_in(personal))
            records = and_(records, AttendanceRecord.user_id.not_in(personal))
        off = resolved.day_off is not None
        groups.append(_Group(workplace, at, records, resolved.windows(), off, reminders))
        for (wid, off, _), ids in by_key.items():
            if wid != workplace.id:
                continue
            windows = days.resolve(wid, day, ids[0]).windows()
            who, theirs = User.id.in_(ids), AttendanceRecord.user_id.in_(ids)
            groups.append(_Group(workplace, who, theirs, windows, off, reminders))
    return groups


async def _cutoffs(
    session: AsyncSession, w: win.ShiftWindows, g: _Group, now: datetime, result: TickResult
) -> None:
    if now >= w.check_in_closes:
        result.absent += await _mark_absent(session, w, g.workplace.id, g.at, result)
    if now >= w.check_out_closes:
        result.forgot_checkout += await _mark_forgot(session, w, g.records)


async def rerun(
    session: AsyncSession, pairs: Iterable[tuple[uuid.UUID, date]], now: datetime
) -> TickResult:
    """Replay the passed cutoffs of these (workplace, date) pairs (active workplaces only), in
    the caller's transaction (which holds the scheduler lock): absents where there is no record,
    open records to forgot check-out. Days off are skipped; no reminders."""
    result = TickResult()
    wanted: dict[uuid.UUID, set[date]] = {}
    for workplace_id, day in pairs:
        wanted.setdefault(workplace_id, set()).add(day)
    if not wanted:
        return result
    workplaces = await _active_workplaces(session)
    every = [d for dates in wanted.values() for d in dates]
    days = await load_days(session, workplaces, min(every), max(every), "all")
    for day in sorted(set(every)):
        for g in await _groups(session, days, workplaces, day):
            if day not in wanted.get(g.workplace.id, ()):
                continue
            for w in g.windows:
                await _cutoffs(session, w, g, now, result)
    return result


async def tick(session: AsyncSession, now: datetime) -> TickResult | None:
    """One pass inside the caller's transaction. None when another worker holds the lock."""
    got = await session.scalar(
        text("SELECT pg_try_advisory_xact_lock(:k)"), {"k": SCHEDULER_LOCK_KEY}
    )
    if not got:
        return None
    result = TickResult()
    day = win.work_date(now, get_settings().business_tz)
    workplaces = await _active_workplaces(session)
    days = await load_days(session, workplaces, day, day, "all")
    # Employees of workplaces with reminders off or a day off today.
    muted: list[ColumnElement[bool]] = []
    for g in await _groups(session, days, workplaces, day):
        if g.off:
            muted.append(g.at)
            continue
        if not g.reminders:
            muted.append(g.at)
        for w in g.windows:
            await _cutoffs(session, w, g, now, result)
            if g.reminders:
                if w.check_in_opens <= now < w.check_in_closes:
                    await _queue_reminders(session, w, "check_in", now, g.at)
                if w.check_out_opens <= now < w.check_out_closes:
                    await _queue_reminders(session, w, "check_out", now, g.at)
    # Never sent late: a reminder whose window closed (downtime) is skipped. Turning a
    # workplace's reminders off (or a day off) also skips its employees' waiting ones.
    untracked = (
        select(User.id)
        .where(User.id == AttendanceReminder.user_id, ~_tracked(AttendanceReminder.work_date))
        .exists()
    )
    skip: ColumnElement[bool] = or_(AttendanceReminder.window_closes_at <= now, untracked)
    if muted:
        skip = or_(skip, AttendanceReminder.user_id.in_(select(User.id).where(or_(*muted))))
    skipped = await session.execute(
        update(AttendanceReminder)
        .where(AttendanceReminder.telegram_status == "pending", skip)
        .values(telegram_status="skipped")
        .returning(AttendanceReminder.id)
    )
    result.skipped = len(skipped.all())
    claimed = await session.execute(
        update(AttendanceReminder)
        .where(
            AttendanceReminder.telegram_status == "pending",
            AttendanceReminder.window_closes_at > now,
        )
        .values(telegram_status="sending")
        .returning(AttendanceReminder.id)
    )
    result.reminders = list(claimed.scalars())
    return result


async def run_tick(
    now: datetime | None = None, runtime: TelegramRuntime | None = None
) -> TickResult | None:
    """One scheduler tick with its own session: commit, then send the claimed reminders."""
    now = now or clock.now()
    request_alerts: list[uuid.UUID] = []
    async with SessionLocal() as session:
        result = await tick(session, now)
        if result is not None:
            # The 1st of the month: remind employees with an eligible balance (once).
            from app.services.request_service import queue_reminders  # noqa: PLC0415

            request_alerts = await queue_reminders(session, now)
        await session.commit()
    if request_alerts:
        from app.bot.notify import deliver  # noqa: PLC0415

        await deliver(request_alerts, runtime)
    if result is not None and result.reminders:
        result.sent = await send_reminders(result.reminders, runtime, now)
    if result is not None and (result.absent or result.forgot_checkout or result.reminders):
        log.info(
            "attendance tick: %d absent, %d forgot check-out, %d reminders %s",
            result.absent,
            result.forgot_checkout,
            len(result.reminders),
            result.sent,
        )
    return result


async def run_forever(get_runtime) -> None:  # noqa: ANN001 (callable returning the runtime)
    """The lifespan's background task: a tick at the start of every minute, forever."""
    while True:
        now = clock.now()
        try:
            await run_tick(now, get_runtime())
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("attendance scheduler tick failed")
        # Sleep until just after the next minute boundary.
        nxt = (now + timedelta(minutes=1)).replace(second=1, microsecond=0)
        await asyncio.sleep(max(1.0, (nxt - clock.now()).total_seconds()))
