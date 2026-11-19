"""Attendance alerts to general managers (bell + Telegram), holders of `attendance.checkin_alerts`.

- **Per event:** every successful Mini App check-in / check-out (`attendance.checked_in`,
  `attendance.checked_out`, `entity_type = attendance_record`), created in the check's
  transaction. Corrections never go through here.
- **Per shift:** when the scheduler records absents (at the check-in cutoff) or forgot
  check-outs (when the check-out window closes), one message per workplace / date / shift /
  cutoff listing the names it recorded (`attendance.shift_absent`,
  `attendance.shift_forgot_checkout`, `entity_type = attendance_shift`). The entity id is a
  uuid5 of that key, and a group that already has an alert of its type is skipped, so re-runs
  and catch-up after downtime never send it twice.

The workplace is named only while more than one workplace is active. Names are stored as they
are and escaped when the message is built (`app.bot.notify`).
"""

import uuid
from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.attendance.telegram import clock_time
from app.models import AttendanceRecord, AttendanceWorkplace, Notification, User
from app.services import notification_service as notifications

RECORD_ENTITY = "attendance_record"
SHIFT_ENTITY = "attendance_shift"
_NAMESPACE = uuid.UUID("5d0b7f3e-8a51-4c1e-9a43-7b2f0c6e1d29")


async def _several_workplaces(session: AsyncSession) -> bool:
    count = await session.scalar(
        select(func.count(AttendanceWorkplace.id)).where(AttendanceWorkplace.is_active)
    )
    return (count or 0) > 1


async def _workplace_name(session: AsyncSession, workplace_id: uuid.UUID | None) -> str | None:
    if workplace_id is None or not await _several_workplaces(session):
        return None
    return await session.scalar(
        select(AttendanceWorkplace.name).where(AttendanceWorkplace.id == workplace_id)
    )


async def event_alert(
    session: AsyncSession, user: User, record: AttendanceRecord, action: str
) -> list[uuid.UUID]:
    """A check-in / check-out alert to every recipient (not committed; queued for Telegram)."""
    gms = await notifications.gm_recipients(session, notifications.ATTENDANCE_ALERT_PERMISSION)
    if not gms:
        return []
    at = record.check_in_at if action == "check_in" else record.check_out_at
    assert at is not None
    payload = {
        "user_id": str(user.id),
        "name": user.full_name,
        "date": record.work_date.isoformat(),
        "shift_code": record.shift_code,
        "time": clock_time(at),
        "workplace": await _workplace_name(session, record.workplace_id),
    }
    if action == "check_in":
        type_ = notifications.CHECKED_IN
        payload |= {"late_minutes": record.late_minutes, "early_minutes": record.early_minutes}
    else:
        type_ = notifications.CHECKED_OUT
        payload |= {"overtime_minutes": record.overtime_minutes}
    return notifications.notify_users(
        session, type_, gms, entity_type=RECORD_ENTITY, entity_id=record.id, payload=payload
    )


@dataclass(frozen=True)
class ShiftKey:
    """One grouped message: a workplace's shift on a date, at one cutoff (employees with their
    own times may have another cutoff for the same shift)."""

    workplace_id: uuid.UUID
    work_date: date
    shift_code: str
    cutoff: datetime

    def entity_id(self) -> uuid.UUID:
        return uuid.uuid5(
            _NAMESPACE,
            f"{self.workplace_id}|{self.work_date.isoformat()}|{self.shift_code}|"
            f"{self.cutoff.isoformat()}",
        )


async def shift_alerts(
    session: AsyncSession, type_: str, groups: dict[ShiftKey, set[uuid.UUID]]
) -> list[uuid.UUID]:
    """One alert per non-empty group not alerted before (not committed; queued for Telegram)."""
    groups = {k: ids for k, ids in groups.items() if ids}
    if not groups:
        return []
    gms = await notifications.gm_recipients(session, notifications.ATTENDANCE_ALERT_PERMISSION)
    if not gms:
        return []
    several = await _several_workplaces(session)
    names = {
        u.id: u.full_name
        for u in await session.scalars(
            select(User).where(User.id.in_({i for ids in groups.values() for i in ids}))
        )
    }
    workplaces = {
        w.id: w.name
        for w in await session.scalars(
            select(AttendanceWorkplace).where(
                AttendanceWorkplace.id.in_({k.workplace_id for k in groups})
            )
        )
    }
    created: list[uuid.UUID] = []
    for key in sorted(groups, key=lambda k: (k.work_date, k.cutoff, k.shift_code)):
        entity_id = key.entity_id()
        done = await session.scalar(
            select(
                exists().where(
                    Notification.type == type_,
                    Notification.entity_type == SHIFT_ENTITY,
                    Notification.entity_id == entity_id,
                )
            )
        )
        if done:
            continue
        payload = {
            "date": key.work_date.isoformat(),
            "shift_code": key.shift_code,
            "cutoff": clock_time(key.cutoff),
            "workplace_id": str(key.workplace_id),
            "workplace": workplaces.get(key.workplace_id) if several else None,
            "names": sorted(names.get(i, "") for i in groups[key]),
        }
        created += notifications.notify_users(
            session, type_, gms, entity_type=SHIFT_ENTITY, entity_id=entity_id, payload=payload
        )
    return created
