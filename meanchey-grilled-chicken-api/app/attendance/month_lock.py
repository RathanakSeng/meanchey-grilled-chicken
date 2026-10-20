"""Month lock: while an employee's request for a month is `pending` or `approved`, that month's
records can't be corrected, added, removed or recreated. A rejection unlocks it."""

import uuid
from collections.abc import Iterable
from datetime import date

from sqlalchemy import ColumnElement, and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, ErrorCode
from app.models import AttendanceRequest

LOCKING = ("pending", "approved")


def month_locked_sql(user_id: ColumnElement[uuid.UUID], day: date) -> ColumnElement[bool]:
    """True when `user_id` has a locking request for the month of `day` (an EXISTS)."""
    return (
        select(AttendanceRequest.id)
        .where(
            AttendanceRequest.user_id == user_id,
            AttendanceRequest.year == day.year,
            AttendanceRequest.month == day.month,
            AttendanceRequest.status.in_(LOCKING),
        )
        .exists()
    )


async def locked_pairs(
    session: AsyncSession, user_ids: Iterable[uuid.UUID]
) -> set[tuple[uuid.UUID, int, int]]:
    """(user, year, month) of every locking request of these users."""
    ids = list(set(user_ids))
    if not ids:
        return set()
    rows = await session.execute(
        select(AttendanceRequest.user_id, AttendanceRequest.year, AttendanceRequest.month).where(
            AttendanceRequest.user_id.in_(ids), AttendanceRequest.status.in_(LOCKING)
        )
    )
    return {(u, y, m) for u, y, m in rows}


async def is_locked(session: AsyncSession, user_id: uuid.UUID, day: date) -> bool:
    return bool(
        await session.scalar(
            select(
                select(AttendanceRequest.id)
                .where(
                    and_(
                        AttendanceRequest.user_id == user_id,
                        AttendanceRequest.year == day.year,
                        AttendanceRequest.month == day.month,
                        AttendanceRequest.status.in_(LOCKING),
                    )
                )
                .exists()
            )
        )
    )


async def ensure_unlocked(session: AsyncSession, user_id: uuid.UUID, day: date) -> None:
    """409 ATTENDANCE_MONTH_LOCKED when the employee's month of `day` is locked."""
    if await is_locked(session, user_id, day):
        raise AppError(
            409,
            ErrorCode.ATTENDANCE_MONTH_LOCKED,
            "This month is locked by an attendance request",
            {"year": day.year, "month": day.month},
        )
