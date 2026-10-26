"""Checking employees' own schedules against their workplace's rules.

An employee's shifts (their override's codes and times on top of the workplace's shifts) must
make a valid day under the workplace's rules on every date the override applies: start < end,
inside the day, no overlap, every derived window inside the day (`windows.validate`).

- **On save** (`problems_from`): from the override's date until the employee's next version,
  at each workplace version in between → `422 ATTENDANCE_SCHEDULE_INVALID`.
- **On a workplace change** (`check_workplaces`, after the new versions are flushed): every
  current or upcoming override of the employees assigned there is checked again; any that
  would break → `409 ATTENDANCE_SCHEDULE_CONFLICT` listing the employees (nothing is saved).
- **A shift code gone from a workplace** (`prune_codes`): removed from the overrides of its
  employees; an override left without shifts inherits them all again.
"""

import uuid
from collections.abc import Iterable, Sequence
from datetime import date
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.attendance import personal as per
from app.attendance import windows as win
from app.attendance.days import Days, load_days
from app.attendance.workplaces import TRACKED_ROLES, today
from app.core.errors import AppError, ErrorCode
from app.models import AttendanceEmployeeOverride, AttendanceWorkplace, User

Problem = tuple[list[str], str]


def _loc(loc: list[str]) -> list[str]:
    """`windows.validate` speaks of `body.shifts.<code>…`; an employee's times are
    `body.shift_times.<code>…` (rule problems stay as they are)."""
    if loc[:2] == ["body", "shifts"]:
        return ["body", "shift_times", *loc[2:]]
    return loc


def defs_problems(defs: Sequence[win.ShiftDef], rules: win.Rules) -> list[Problem]:
    return [(_loc(loc), msg) for loc, msg in win.validate(defs, rules)]


def problems_from(
    days: Days,
    workplace_id: uuid.UUID,
    o: AttendanceEmployeeOverride,
    until: date | None,
) -> tuple[date, list[Problem]] | None:
    """The first date (from `o.effective_from`, before `until`) where `o` makes an invalid day
    under the workplace's version then, with the problems."""
    dates = {o.effective_from} | {
        v.effective_from
        for v in days.versions.get(workplace_id, [])
        if v.effective_from > o.effective_from and (until is None or v.effective_from < until)
    }
    for d in sorted(dates):
        schedule = days.schedule(workplace_id, d)
        problems = defs_problems(per.personal_defs(schedule.defs, o), schedule.rules)
        if problems:
            return d, problems
    return None


def invalid(user: User, day: date, problems: list[Problem]) -> AppError:
    return AppError(
        422,
        ErrorCode.ATTENDANCE_SCHEDULE_INVALID,
        problems[0][1],
        {
            "user_id": str(user.id),
            "name": user.full_name,
            "date": day.isoformat(),
            "fields": [{"loc": loc, "type": "value_error", "msg": msg} for loc, msg in problems],
        },
    )


async def _assigned(session: AsyncSession, workplaces: Sequence[AttendanceWorkplace]) -> list[User]:
    """Staff and supervisors who check in at these workplaces (the default one also takes
    those without an active workplace)."""
    ids = [w.id for w in workplaces]
    active = select(AttendanceWorkplace.id).where(AttendanceWorkplace.is_active)
    conditions = [User.workplace_id.in_(ids)]
    if any(w.is_default for w in workplaces):
        conditions += [User.workplace_id.is_(None), User.workplace_id.not_in(active)]
    return list(
        await session.scalars(select(User).where(User.role.in_(TRACKED_ROLES), or_(*conditions)))
    )


def _upcoming(versions: Sequence[AttendanceEmployeeOverride], day: date):  # noqa: ANN202
    """The version in effect on `day` and the later ones, each with the next one's date."""
    current = per.override_on(versions, day)
    kept = [v for v in versions if v is current or v.effective_from > day]
    return [
        (v, kept[n + 1].effective_from if n + 1 < len(kept) else None) for n, v in enumerate(kept)
    ]


async def check_workplaces(
    session: AsyncSession, workplaces: Sequence[AttendanceWorkplace]
) -> None:
    """After a change to these workplaces' shifts or rules (flushed, not committed): refuse it
    when a current or upcoming override of their employees would make an invalid day."""
    if not workplaces:
        return
    await session.flush()
    users = await _assigned(session, workplaces)
    if not users:
        return
    day = today()
    by_id = {w.id: w for w in workplaces}
    default = next((w for w in workplaces if w.is_default), None)
    days = await load_days(session, workplaces, day, day, [u.id for u in users])
    conflicts: list[dict[str, Any]] = []
    for u in users:
        versions = days.overrides.get(u.id, [])
        if not versions:
            continue
        wid = u.workplace_id if u.workplace_id in by_id else (default.id if default else None)
        if wid is None:
            continue
        for o, until in _upcoming(versions, day):
            if o.shift_codes is None and o.shift_times is None:
                continue
            found = problems_from(days, wid, o, until)
            if found:
                conflicts.append(
                    {
                        "user_id": str(u.id),
                        "name": u.full_name,
                        "date": max(found[0], day).isoformat(),
                        "message": found[1][0][1],
                    }
                )
                break
    if conflicts:
        raise AppError(
            409,
            ErrorCode.ATTENDANCE_SCHEDULE_CONFLICT,
            "Some employees' own shift times don't fit the new schedule",
            {"employees": conflicts},
        )


async def prune_codes(
    session: AsyncSession, workplaces: Sequence[AttendanceWorkplace], codes: Iterable[str]
) -> list[dict[str, str]]:
    """Drop shift `codes` (gone from these workplaces) from their employees' current and
    upcoming overrides. Returns the employees affected."""
    gone = set(codes)
    if not gone or not workplaces:
        return []
    users = {u.id: u for u in await _assigned(session, workplaces)}
    if not users:
        return []
    day = today()
    rows = list(
        await session.scalars(
            select(AttendanceEmployeeOverride)
            .where(AttendanceEmployeeOverride.user_id.in_(users))
            .order_by(AttendanceEmployeeOverride.effective_from)
            .with_for_update()
        )
    )
    by_user: dict[uuid.UUID, list[AttendanceEmployeeOverride]] = {}
    for o in rows:
        by_user.setdefault(o.user_id, []).append(o)
    affected: dict[uuid.UUID, dict[str, str]] = {}
    for user_id, versions in by_user.items():
        for o, _ in _upcoming(versions, day):
            touched = False
            if o.shift_codes and gone & set(o.shift_codes):
                left = [c for c in o.shift_codes if c not in gone]
                o.shift_codes = left or None
                touched = True
            if o.shift_times and gone & set(o.shift_times):
                left_times = {c: t for c, t in o.shift_times.items() if c not in gone}
                o.shift_times = left_times or None
                touched = True
            if touched:
                u = users[user_id]
                affected[user_id] = {"user_id": str(u.id), "name": u.full_name}
    return list(affected.values())
