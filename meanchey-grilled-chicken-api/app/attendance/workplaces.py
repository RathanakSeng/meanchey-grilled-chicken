"""Workplaces, their schedule versions and who is tracked.

Each workplace has a schedule **per date**: the latest `attendance_schedule_versions` row with
`effective_from` <= that date (dates before its first version use the first). A version holds the
tracked weekdays, both shifts and the rules; `Schedule` turns it into the pure definitions of
`app.attendance.windows`. Holidays and days off are in `app.attendance.days`.

Kept apart from `services/attendance_service.py` so `user_service` can assign workplaces on
create / role change without an import cycle.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, time
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.attendance import clock
from app.attendance import windows as win
from app.config import get_settings
from app.core.errors import AppError, ErrorCode
from app.models import AttendanceScheduleVersion, AttendanceWorkplace, Role, User

TRACKED_ROLES = frozenset({Role.STAFF, Role.SUPERVISOR})
DEFAULT_WORKPLACE_NAME = "Mean Chey"
ALL_WEEKDAYS = (1, 2, 3, 4, 5, 6, 7)
DEFAULT_SHIFTS: tuple[dict[str, Any], ...] = (
    {
        "code": "morning",
        "name_km": "វេនព្រឹក",
        "name_en": "Morning shift",
        "start_time": "07:00",
        "end_time": "12:00",
        "position": 1,
    },
    {
        "code": "afternoon",
        "name_km": "វេនរសៀល",
        "name_en": "Afternoon shift",
        "start_time": "13:00",
        "end_time": "15:00",
        "position": 2,
    },
)
RULE_FIELDS = (
    "open_before_min",
    "absent_after_min",
    "checkout_window_min",
    "max_accuracy_m",
    "reminders_enabled",
    "count_early_checkin",
    "count_overtime",
)
DEFAULT_RULES: dict[str, Any] = {
    "open_before_min": 30,
    "absent_after_min": 45,
    "checkout_window_min": 59,
    "max_accuracy_m": 100,
    "reminders_enabled": True,
    "count_early_checkin": True,
    "count_overtime": True,
}
# Everything a version holds besides its workplace and date.
VERSION_FIELDS = ("weekdays", "shifts", *RULE_FIELDS)


def is_tracked(user: User) -> bool:
    """Attendance is recorded for active staff and supervisors (never the GM or superadmin)."""
    return user.is_active and user.role in TRACKED_ROLES


def today() -> date:
    return win.work_date(clock.now(), get_settings().business_tz)


# --- Schedules -----------------------------------------------------------------------------------


def parse_hm(value: str) -> time:
    return time.fromisoformat(value)


def shift_def(s: dict[str, Any]) -> win.ShiftDef:
    return win.ShiftDef(
        s["code"],
        s["name_km"],
        s["name_en"],
        parse_hm(s["start_time"]),
        parse_hm(s["end_time"]),
        s["position"],
    )


def rules_of(v: AttendanceScheduleVersion) -> win.Rules:
    return win.Rules(*(getattr(v, f) for f in RULE_FIELDS))


@dataclass
class Schedule:
    """A workplace with the schedule version in effect on some date."""

    workplace: AttendanceWorkplace
    version: AttendanceScheduleVersion

    @property
    def defs(self) -> list[win.ShiftDef]:
        return sorted((shift_def(s) for s in self.version.shifts), key=lambda d: d.position)

    @property
    def rules(self) -> win.Rules:
        return rules_of(self.version)

    @property
    def weekdays(self) -> list[int]:
        return sorted(self.version.weekdays)

    def windows(self, day: date) -> list[win.ShiftWindows]:
        return win.day_windows(self.defs, self.rules, day, get_settings().business_tz)

    def shift(self, code: str) -> win.ShiftDef | None:
        return next((d for d in self.defs if d.code == code), None)


def version_on(
    versions: Sequence[AttendanceScheduleVersion], day: date
) -> AttendanceScheduleVersion | None:
    """The version in effect on `day` (`versions` sorted by `effective_from`); before the first
    one, the first."""
    found = None
    for v in versions:
        if v.effective_from <= day:
            found = v
        else:
            break
    return found or (versions[0] if versions else None)


async def versions_of(
    session: AsyncSession, workplace_ids: Sequence[uuid.UUID], *, lock: bool = False
) -> dict[uuid.UUID, list[AttendanceScheduleVersion]]:
    """Each workplace's versions, oldest first."""
    out: dict[uuid.UUID, list[AttendanceScheduleVersion]] = {i: [] for i in workplace_ids}
    if not workplace_ids:
        return out
    stmt = (
        select(AttendanceScheduleVersion)
        .where(AttendanceScheduleVersion.workplace_id.in_(workplace_ids))
        .order_by(AttendanceScheduleVersion.effective_from)
    )
    if lock:
        stmt = stmt.with_for_update()
    for v in await session.scalars(stmt):
        out[v.workplace_id].append(v)
    return out


def default_version(workplace_id: uuid.UUID, effective_from: date) -> AttendanceScheduleVersion:
    return AttendanceScheduleVersion(
        id=uuid.uuid4(),
        workplace_id=workplace_id,
        effective_from=effective_from,
        weekdays=list(ALL_WEEKDAYS),
        shifts=[dict(s) for s in DEFAULT_SHIFTS],
        **DEFAULT_RULES,
    )


def copy_version(
    source: AttendanceScheduleVersion,
    workplace_id: uuid.UUID,
    effective_from: date,
    created_by: uuid.UUID | None = None,
) -> AttendanceScheduleVersion:
    return AttendanceScheduleVersion(
        workplace_id=workplace_id,
        effective_from=effective_from,
        created_by=created_by,
        **{f: _copy(getattr(source, f)) for f in VERSION_FIELDS},
    )


def _copy(value: Any) -> Any:
    if isinstance(value, list):
        return [dict(x) if isinstance(x, dict) else x for x in value]
    return value


async def load_schedule(
    session: AsyncSession, workplace: AttendanceWorkplace, day: date
) -> Schedule:
    versions = (await versions_of(session, [workplace.id]))[workplace.id]
    version = version_on(versions, day)
    if version is None:
        # Never left without one (bootstrap / create add it); repair if it happens.
        version = default_version(workplace.id, day)
        session.add(version)
        await session.flush()
    return Schedule(workplace, version)


# --- Defaults and the workplace assignment -------------------------------------------------------


async def ensure_defaults(session: AsyncSession) -> None:
    """Bootstrap: the default workplace when missing (the migration seeds it; it is re-created
    after e.g. a reset), a schedule version for every workplace without one (from its creation
    date), and the default workplace for every staff member and supervisor without one. Never
    overwrites anything."""
    default = await default_workplace(session)
    if default is None:
        default = AttendanceWorkplace(name=DEFAULT_WORKPLACE_NAME, is_default=True)
        session.add(default)
        await session.flush()
        await session.refresh(default)
    missing = await session.scalars(
        select(AttendanceWorkplace).where(
            ~select(AttendanceScheduleVersion.id)
            .where(AttendanceScheduleVersion.workplace_id == AttendanceWorkplace.id)
            .exists()
        )
    )
    zone = get_settings().business_tz
    for w in missing:
        session.add(default_version(w.id, w.created_at.astimezone(zone).date()))
    await session.execute(
        update(User)
        .where(User.role.in_(TRACKED_ROLES), User.workplace_id.is_(None))
        .values(workplace_id=default.id)
    )


async def default_workplace(session: AsyncSession) -> AttendanceWorkplace | None:
    return await session.scalar(
        select(AttendanceWorkplace)
        .where(AttendanceWorkplace.is_default, AttendanceWorkplace.is_active)
        .limit(1)
    )


async def active_workplace(session: AsyncSession, workplace_id: uuid.UUID) -> AttendanceWorkplace:
    """The workplace to assign someone to: it must exist and not be archived."""
    w = await session.get(AttendanceWorkplace, workplace_id)
    if w is None:
        raise AppError(404, ErrorCode.ATTENDANCE_WORKPLACE_NOT_FOUND, "Workplace not found")
    if not w.is_active:
        raise AppError(409, ErrorCode.WORKPLACE_ARCHIVED, "The workplace is archived")
    return w


async def assign_workplace(
    session: AsyncSession, user: User, workplace_id: uuid.UUID | None = None
) -> bool:
    """Staff and supervisors: `workplace_id` when given (an active workplace), else they keep
    theirs while it is active, else the default. Other roles keep whatever they had (it is
    unused while they aren't tracked); giving them one is refused. Called on create, edit,
    role change and reactivation. Returns whether the workplace changed."""
    # Set through the relationship (not only the id) so `UserOut.workplace` is current without a
    # lazy load.
    if user.role not in TRACKED_ROLES:
        if workplace_id is not None:
            raise AppError(
                422,
                ErrorCode.VALIDATION_ERROR,
                "Only staff and supervisors have a workplace",
                {
                    "fields": [
                        {
                            "loc": ["body", "workplace_id"],
                            "type": "value_error",
                            "msg": "Only staff and supervisors have a workplace",
                        }
                    ]
                },
            )
        return False
    if workplace_id is not None:
        target = await active_workplace(session, workplace_id)
    else:
        current = (
            await session.get(AttendanceWorkplace, user.workplace_id)
            if user.workplace_id is not None
            else None
        )
        if current is not None and current.is_active:
            return False
        target = await default_workplace(session)
        if target is None:
            return False
    if user.workplace_id == target.id:
        return False
    user.workplace = target
    user.workplace_id = target.id
    return True


async def user_workplace(session: AsyncSession, user: User) -> AttendanceWorkplace | None:
    """Where a tracked employee checks in: their workplace while active, else the default."""
    if user.workplace_id is not None:
        workplace = await session.get(AttendanceWorkplace, user.workplace_id)
        if workplace is not None and workplace.is_active:
            return workplace
    return await default_workplace(session)
