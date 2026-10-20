"""Who is tracked on a date: the one rule every attendance feature asks.

An employee is tracked on a date when all hold: the role is staff or supervisor, the account is
active, the date is on or after `attendance_start_date`, and the date is not inside an untracked
period (a supervisor whose attendance was switched off, `attendance_untracked_periods`). The
workplace's own day-off rules (weekdays, holidays) are separate: `app.attendance.days`.

Used by the scheduler (SQL: `tracked_on_sql`), check-in / check-out, `me/today`, the bot's
`/start` button, the day view and the summaries (Python: `status_on`)."""

import uuid
from collections.abc import Iterable
from datetime import date, timedelta
from typing import Any, Literal

from sqlalchemy import ColumnElement, and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.attendance.workplaces import TRACKED_ROLES
from app.models import AttendanceUntrackedPeriod, User

Status = Literal["tracked", "inactive", "not_required", "not_started", "untracked"]
# (from_date, to_date): to_date None = ongoing.
Period = tuple[date, date | None]


async def periods_of(
    session: AsyncSession, user_ids: Iterable[uuid.UUID]
) -> dict[uuid.UUID, list[Period]]:
    ids = list(user_ids)
    out: dict[uuid.UUID, list[Period]] = {}
    if not ids:
        return out
    rows = await session.execute(
        select(
            AttendanceUntrackedPeriod.user_id,
            AttendanceUntrackedPeriod.from_date,
            AttendanceUntrackedPeriod.to_date,
        )
        .where(AttendanceUntrackedPeriod.user_id.in_(ids))
        .order_by(AttendanceUntrackedPeriod.from_date)
    )
    for user_id, start, end in rows:
        out.setdefault(user_id, []).append((start, end))
    return out


def in_period(periods: Iterable[Period], day: date) -> bool:
    return any(start <= day and (end is None or day <= end) for start, end in periods)


def status_on(user: User, day: date, periods: Iterable[Period] = ()) -> Status:
    """Why `user` is (not) tracked on `day`. `tracked` is the only status that records
    attendance; a missing start date counts as "since forever"."""
    if user.role not in TRACKED_ROLES:
        return "not_required"
    if not user.is_active:
        return "inactive"
    if user.attendance_start_date is not None and day < user.attendance_start_date:
        return "not_started"
    if in_period(periods, day):
        return "untracked"
    return "tracked"


def tracked_on(user: User, day: date, periods: Iterable[Period] = ()) -> bool:
    return status_on(user, day, periods) == "tracked"


def current_period(periods: Iterable[Period]) -> Period | None:
    """The ongoing untracked period, if any."""
    return next((p for p in periods if p[1] is None), None)


def tracked_on_sql(day: Any, *extra: ColumnElement[bool]) -> ColumnElement[bool]:
    """The same rule as a SQL condition on `User` (`day`: a date or a date column), for the
    scheduler. `extra` conditions are and-ed."""
    in_untracked = (
        select(AttendanceUntrackedPeriod.id)
        .where(
            AttendanceUntrackedPeriod.user_id == User.id,
            AttendanceUntrackedPeriod.from_date <= day,
            or_(
                AttendanceUntrackedPeriod.to_date.is_(None),
                AttendanceUntrackedPeriod.to_date >= day,
            ),
        )
        .exists()
    )
    return and_(
        User.is_active,
        User.role.in_(TRACKED_ROLES),
        or_(User.attendance_start_date.is_(None), User.attendance_start_date <= day),
        ~in_untracked,
        *extra,
    )


def yesterday(day: date) -> date:
    return day - timedelta(days=1)
