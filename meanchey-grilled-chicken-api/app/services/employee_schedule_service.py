"""Employees' own schedules (override versions) and holiday work exceptions.

- **Override versions** (`attendance_employee_overrides`): per employee, from a date (today by
  default, never the past): `weekdays`, `shift_codes`, `shift_times`, each null = inherit the
  workplace's. A bulk write creates (or replaces, same date) one version per employee: a field
  left out keeps the value in effect then, `"inherit"` clears it; the changed fields are also
  written into the employee's later upcoming versions, so the change holds from that date on.
  Reset = every field inherits (later upcoming versions are deleted). Upcoming versions can be
  deleted; current or past ones can't.
- **Effective today:** only today's shifts whose check-in hasn't opened (and that have no
  record) follow the new setting; the others keep the previous one that day (`kept_shifts`).
- **Validation:** the employee's shifts must make a valid day under the workplace's rules on
  every date the version applies (`app.attendance.overrides`) → `ATTENDANCE_SCHEDULE_INVALID`.
- **Holiday exceptions** (`attendance_holiday_exceptions`): employees who work on days of a
  holiday (today or later), with their normal shifts or chosen ones / times. Removing one for
  today makes the day off for them again: their records that day are removed (corrected ones
  kept, locked months left alone), as when a holiday is added.
- **Scope:** the role hierarchy (GM / superadmin → staff and supervisors, a supervisor →
  staff); hidden accounts are 404.
- **Notifications** (bell + Telegram): the employee hears of each change.
"""

import uuid
from collections.abc import Iterable, Sequence
from datetime import date, timedelta
from typing import Any

from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.attendance import clock
from app.attendance import overrides as ovr
from app.attendance import personal as per
from app.attendance import windows as win
from app.attendance.days import Days, Resolved, load_days
from app.attendance.month_lock import locked_pairs
from app.attendance.tracking import status_on
from app.attendance.workplaces import RULE_FIELDS, TRACKED_ROLES, today, user_workplace
from app.config import get_settings
from app.core.errors import AppError, ErrorCode
from app.models import (
    AttendanceEmployeeOverride,
    AttendanceHoliday,
    AttendanceHolidayException,
    AttendanceRecord,
    AttendanceWorkplace,
    Role,
    User,
    utcnow,
)
from app.permissions.hierarchy import MANAGEABLE_ROLES, ensure_can_manage
from app.schemas.attendance import HolidayBrief, RulesOut, UserWorkplace, hm
from app.schemas.attendance_schedule import (
    EmployeeResetIn,
    EmployeeScheduleDetail,
    EmployeeScheduleIn,
    EmployeeScheduleList,
    EmployeeScheduleRow,
    EmployeeScheduleWriteOut,
    HolidayExceptionIn,
    HolidayExceptionOut,
    HolidayExceptionWriteOut,
    OverrideVersionOut,
    PersonalShiftOut,
    PreviewDay,
    PreviewShift,
    ScheduleSummaryOut,
    ShiftTimeOut,
)
from app.schemas.common import UserRef
from app.services.attendance_service import _windows_out, day_off_out, user_refs
from app.services.audit_service import record as audit
from app.services.notification_service import (
    HOLIDAY_OFF,
    HOLIDAY_WORK,
    SCHEDULE_CHANGED,
    notify_users,
)
from app.services.scheduling_service import (
    _effective,
    _field_error,
    _lock,
    _snapshot,
    active_workplaces,
)
from app.services.user_service import get_user_or_404

ENTITY_SCHEDULE = "attendance_schedule"
ENTITY_HOLIDAY = "attendance_holiday"
PREVIEW_DAYS = 7


# --- Helpers -------------------------------------------------------------------------------------


def _scope_roles(viewer: User) -> frozenset[Role]:
    return frozenset(MANAGEABLE_ROLES[viewer.role] & TRACKED_ROLES)


async def _target(session: AsyncSession, actor: User, user_id: uuid.UUID) -> User:
    target = await get_user_or_404(session, user_id, actor)
    ensure_can_manage(actor, target)
    if target.role not in TRACKED_ROLES:
        raise AppError(
            422, ErrorCode.ATTENDANCE_NOT_REQUIRED, "Attendance isn't recorded for this account"
        )
    return target


async def _targets(session: AsyncSession, actor: User, ids: Iterable[uuid.UUID]) -> list[User]:
    return [await _target(session, actor, i) for i in dict.fromkeys(ids)]


async def _workplace(session: AsyncSession, user: User) -> AttendanceWorkplace:
    workplace = await user_workplace(session, user)
    if workplace is None:
        raise AppError(409, ErrorCode.ATTENDANCE_WORKPLACE_NOT_SET, "The employee has no workplace")
    return workplace


async def _versions(
    session: AsyncSession, user_ids: Iterable[uuid.UUID], *, lock: bool = False
) -> dict[uuid.UUID, list[AttendanceEmployeeOverride]]:
    """Every override version of these employees, oldest first."""
    ids = list(user_ids)
    out: dict[uuid.UUID, list[AttendanceEmployeeOverride]] = {i: [] for i in ids}
    if not ids:
        return out
    stmt = (
        select(AttendanceEmployeeOverride)
        .where(AttendanceEmployeeOverride.user_id.in_(ids))
        .order_by(AttendanceEmployeeOverride.effective_from)
    )
    if lock:
        stmt = stmt.with_for_update()
    for o in await session.scalars(stmt):
        out[o.user_id].append(o)
    return out


def _times_value(value: Any) -> dict[str, dict[str, str]] | None:
    if not value:
        return None
    return {
        code: {"start_time": hm(t.start_time), "end_time": hm(t.end_time)}
        for code, t in sorted(value.items())
    }


def summary_out(r: Resolved) -> ScheduleSummaryOut:
    """Weekdays and the shifts worked on a working day (whatever the weekday / holiday)."""
    windows = {
        w.code: w for w in win.day_windows(r.normal, r.rules, r.day, get_settings().business_tz)
    }
    return ScheduleSummaryOut(
        weekdays=r.weekdays,
        shifts=[
            PersonalShiftOut(
                code=d.code,  # type: ignore[arg-type]
                name_km=d.name_km,
                name_en=d.name_en,
                start_time=d.start,
                end_time=d.end,
                windows=_windows_out(windows[d.code]),
            )
            for d in r.normal
        ],
        custom=r.custom,
    )


def _version_out(
    o: AttendanceEmployeeOverride, refs: dict[uuid.UUID, UserRef]
) -> OverrideVersionOut:
    return OverrideVersionOut(
        id=o.id,
        effective_from=o.effective_from,
        weekdays=sorted(o.weekdays) if o.weekdays is not None else None,
        shift_codes=o.shift_codes,  # type: ignore[arg-type]
        shift_times=(
            {c: ShiftTimeOut(**t) for c, t in o.shift_times.items()}  # type: ignore[misc]
            if o.shift_times is not None
            else None
        ),
        created_by=refs.get(o.created_by) if o.created_by else None,
        created_at=o.created_at,
    )


def _preview_shifts(defs: Sequence[win.ShiftDef]) -> list[PreviewShift]:
    return [
        PreviewShift(code=d.code, start_time=d.start, end_time=d.end)  # type: ignore[arg-type]
        for d in defs
    ]


def _shifts_payload(defs: Sequence[win.ShiftDef]) -> list[dict[str, str]]:
    return [{"code": d.code, "start_time": hm(d.start), "end_time": hm(d.end)} for d in defs]


def _effective_workplaces(
    workplaces: Sequence[AttendanceWorkplace],
) -> tuple[dict[uuid.UUID, AttendanceWorkplace], AttendanceWorkplace | None]:
    by_id = {w.id: w for w in workplaces}
    return by_id, next((w for w in workplaces if w.is_default), None)


def _where(
    u: User, by_id: dict[uuid.UUID, AttendanceWorkplace], default: AttendanceWorkplace | None
) -> AttendanceWorkplace | None:
    if u.workplace_id in by_id:
        return by_id[u.workplace_id]  # type: ignore[index]
    return default


# --- Reading -------------------------------------------------------------------------------------


async def schedule_summary(session: AsyncSession, user: User) -> ScheduleSummaryOut | None:
    """The employee's schedule today (`UserOut.attendance_schedule_summary`)."""
    if user.role not in TRACKED_ROLES:
        return None
    workplace = await user_workplace(session, user)
    if workplace is None:
        return None
    day = today()
    days = await load_days(session, [workplace], day, day, [user.id])
    return summary_out(days.resolve(workplace.id, day, user.id))


async def list_employees(
    session: AsyncSession,
    viewer: User,
    workplace_ids: Sequence[uuid.UUID] | None,
    custom_only: bool,
    q: str | None,
) -> EmployeeScheduleList:
    day = today()
    workplaces = await active_workplaces(session)
    by_id, default = _effective_workplaces(workplaces)
    stmt = select(User).where(User.is_active, User.role.in_(_scope_roles(viewer)))
    if q and q.strip():
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(User.full_name.ilike(like), User.telegram_username.ilike(like)))
    users = [
        u
        for u in await session.scalars(stmt)
        if status_on(u, day, u.attendance_periods) != "untracked"
    ]
    wanted = set(workplace_ids or ())
    placed = [(u, _where(u, by_id, default)) for u in users]
    placed = [(u, w) for u, w in placed if w is not None and (not wanted or w.id in wanted)]
    days = await load_days(session, workplaces, day, day, [u.id for u, _ in placed])
    upcoming: dict[uuid.UUID, tuple[int, date]] = {
        user_id: (count, first)
        for user_id, count, first in await session.execute(
            select(
                AttendanceEmployeeOverride.user_id,
                func.count(),
                func.min(AttendanceEmployeeOverride.effective_from),
            )
            .where(AttendanceEmployeeOverride.effective_from > day)
            .group_by(AttendanceEmployeeOverride.user_id)
        )
    }
    items = []
    for u, w in placed:
        assert w is not None
        r = days.resolve(w.id, day, u.id)
        count, first = upcoming.get(u.id, (0, None))
        if custom_only and not r.custom and not count:
            continue
        items.append(
            EmployeeScheduleRow(
                user=UserRef.model_validate(u),
                role=u.role,
                position=u.position,
                workplace=UserWorkplace(id=w.id, name=w.name),
                summary=summary_out(r),
                upcoming=count,
                next_change=first,
            )
        )
    items.sort(key=lambda row: (row.role != Role.SUPERVISOR, row.user.full_name.casefold()))
    return EmployeeScheduleList(
        today=day,
        items=items,
        workplace_options=[UserWorkplace(id=w.id, name=w.name) for w in workplaces],
    )


async def detail(
    session: AsyncSession, viewer: User, user_id: uuid.UUID, start: date | None
) -> EmployeeScheduleDetail:
    target = await _target(session, viewer, user_id)
    workplace = await _workplace(session, target)
    day = today()
    start = start or day
    end = start + timedelta(days=PREVIEW_DAYS - 1)
    days = await load_days(session, [workplace], min(day, start), max(day, end), [target.id])
    versions = (await _versions(session, [target.id]))[target.id]
    days.overrides[target.id] = versions
    current = per.override_on(versions, day)
    refs = await user_refs(session, {o.created_by for o in versions})
    preview = []
    for n in range(PREVIEW_DAYS):
        d = start + timedelta(days=n)
        r = days.resolve(workplace.id, d, target.id)
        holidays = days.holidays_on(workplace.id, d)
        works = r.exception is not None and r.day_off is None and holidays
        preview.append(
            PreviewDay(
                date=d,
                shifts=_preview_shifts(r.defs),
                day_off=day_off_out(r.day_off),
                works_on_holiday=(
                    HolidayBrief(
                        id=holidays[0].id, name_km=holidays[0].name_km, name_en=holidays[0].name_en
                    )
                    if works
                    else None
                ),
            )
        )
    version = days.version(workplace.id, day)
    return EmployeeScheduleDetail(
        user=UserRef.model_validate(target),
        role=target.role,
        position=target.position,
        workplace=UserWorkplace(id=workplace.id, name=workplace.name),
        today=day,
        schedule=summary_out(days.resolve(workplace.id, day, target.id)),
        workplace_schedule=summary_out(days.resolve(workplace.id, day)),
        rules=RulesOut(**{f: getattr(version, f) for f in RULE_FIELDS}),
        current=_version_out(current, refs) if current else None,
        upcoming=[_version_out(o, refs) for o in versions if o.effective_from > day],
        preview=preview,
    )


# --- Writing versions ----------------------------------------------------------------------------


def _shown(field: str, value: Any) -> Any:
    if value is None:
        return "inherit"
    if field == "shift_times":
        return {c: f"{t['start_time']}–{t['end_time']}" for c, t in sorted(value.items())}
    return value


def _validate_chain(
    user: User,
    days: Days,
    workplace_id: uuid.UUID,
    versions: list[AttendanceEmployeeOverride],
    since: date,
) -> None:
    """Every version from `since` on must make a valid day until the next one."""
    for n, o in enumerate(versions):
        if o.effective_from < since or (o.shift_codes is None and o.shift_times is None):
            continue
        until = versions[n + 1].effective_from if n + 1 < len(versions) else None
        found = ovr.problems_from(days, workplace_id, o, until)
        if found:
            raise ovr.invalid(user, found[0], found[1])


async def _kept_today(
    session: AsyncSession, user: User, before: Resolved, after: Resolved
) -> dict[str, Any] | None:
    """The shifts of today that already opened (or have a record) and would change: they keep
    the previous setting today (`None` = not worked today)."""
    now = clock.now()
    recorded = set(
        await session.scalars(
            select(AttendanceRecord.shift_code).where(
                AttendanceRecord.user_id == user.id, AttendanceRecord.work_date == before.day
            )
        )
    )
    old = {w.code: w for w in before.windows()}
    new = {w.code: w for w in after.windows()}
    kept: dict[str, Any] = {}
    for code in sorted(old.keys() | new.keys()):
        ow, nw = old.get(code), new.get(code)
        opened = (
            code in recorded
            or (ow is not None and ow.check_in_opens <= now)
            or (nw is not None and nw.check_in_opens <= now)
        )
        same = ow is not None and nw is not None and (ow.start, ow.end) == (nw.start, nw.end)
        if opened and not same:
            kept[code] = per.times_of([ow.shift])[code] if ow is not None else None
    return kept or None


async def _write_one(
    session: AsyncSession,
    actor: User,
    user: User,
    versions: list[AttendanceEmployeeOverride],
    effective: date,
    values: dict[str, Any],
    reset: bool,
) -> tuple[dict[str, Any], Resolved] | None:
    """Write `values` into the user's version on `effective` (and their later upcoming ones).
    Returns the changes and the schedule from then on, or None when nothing changes."""
    day = today()
    same = next((v for v in versions if v.effective_from == effective), None)
    source = same or per.override_on(versions, effective)
    before = {f: getattr(source, f) if source else None for f in per.FIELDS}
    after = {**before, **values}
    later = [v for v in versions if v.effective_from > effective]
    later_changed = (
        len(later)
        if reset
        else sum(any(getattr(v, f) != n for f, n in values.items()) for v in later)
    )
    if after == before and not later_changed:
        return None
    workplace = await _workplace(session, user)
    days = await load_days(session, [workplace], day, max(day, effective), [user.id])
    days.overrides[user.id] = list(versions)
    previous = days.resolve(workplace.id, day, user.id) if effective == day else None

    if same is None:
        same = AttendanceEmployeeOverride(
            id=uuid.uuid4(), user_id=user.id, effective_from=effective
        )
        session.add(same)
        versions.append(same)
    for f in per.FIELDS:
        setattr(same, f, after[f])
    same.kept_shifts = None
    same.created_by = actor.id
    same.created_at = utcnow()
    for v in later:
        if reset:
            versions.remove(v)
            await session.delete(v)
        else:
            for f, n in values.items():
                setattr(v, f, n)
    versions.sort(key=lambda v: v.effective_from)
    days.overrides[user.id] = versions
    _validate_chain(user, days, workplace.id, versions, effective)
    if previous is not None:
        same.kept_shifts = await _kept_today(
            session, user, previous, days.resolve(workplace.id, day, user.id)
        )
    changes = {
        f: [_shown(f, before[f]), _shown(f, after[f])] for f in per.FIELDS if before[f] != after[f]
    }
    if later_changed:
        changes["later_versions"] = later_changed
    return changes, days.resolve(workplace.id, effective, user.id)


def _notify_change(
    session: AsyncSession, actor: User, user: User, effective: date, r: Resolved
) -> None:
    notify_users(
        session,
        SCHEDULE_CHANGED,
        [user],
        entity_type=ENTITY_SCHEDULE,
        entity_id=user.id,
        payload={
            "effective_from": effective.isoformat(),
            "weekdays": r.weekdays,
            "shifts": _shifts_payload(r.normal),
            "custom": list(r.custom),
            "actor_id": str(actor.id),
        },
    )


async def _write(
    session: AsyncSession,
    actor: User,
    user_ids: Sequence[uuid.UUID],
    effective_from: date | None,
    values: dict[str, Any],
    action: str,
    reset: bool = False,
) -> EmployeeScheduleWriteOut:
    await _lock(session)
    day = today()
    effective = _effective(effective_from, day)
    targets = await _targets(session, actor, user_ids)
    versions = await _versions(session, [u.id for u in targets], lock=True)
    changed: list[uuid.UUID] = []
    unchanged: list[uuid.UUID] = []
    changes: dict[str, Any] = {}
    for u in targets:
        done = await _write_one(session, actor, u, versions[u.id], effective, values, reset)
        if done is None:
            unchanged.append(u.id)
            continue
        changed.append(u.id)
        changes[u.full_name] = done[0]
        _notify_change(session, actor, u, effective, done[1])
    if changed:
        audit(
            session,
            action,
            actor_id=actor.id,
            target_user_id=changed[0] if len(changed) == 1 else None,
            details={
                "users": [u.full_name for u in targets if u.id in changed],
                "user_ids": [str(i) for i in changed],
                "effective_from": effective.isoformat(),
                "changes": changes,
            },
        )
    await session.commit()
    return EmployeeScheduleWriteOut(effective_from=effective, changed=changed, unchanged=unchanged)


def _values(body: EmployeeScheduleIn) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for f in per.FIELDS:
        if f not in body.model_fields_set:
            continue
        value = getattr(body, f)
        if value == per.INHERIT:
            out[f] = None
        elif f == "shift_times":
            out[f] = _times_value(value)
        else:
            out[f] = list(value)
    return out


async def update(
    session: AsyncSession, actor: User, body: EmployeeScheduleIn
) -> EmployeeScheduleWriteOut:
    return await _write(
        session,
        actor,
        body.user_ids,
        body.effective_from,
        _values(body),
        "attendance.employee_schedule_update",
    )


async def reset(
    session: AsyncSession, actor: User, body: EmployeeResetIn
) -> EmployeeScheduleWriteOut:
    return await _write(
        session,
        actor,
        body.user_ids,
        body.effective_from,
        dict.fromkeys(per.FIELDS),
        "attendance.employee_schedule_reset",
        reset=True,
    )


async def delete_version(
    session: AsyncSession, actor: User, user_id: uuid.UUID, version_id: uuid.UUID
) -> None:
    """Only an upcoming version (effective after today)."""
    target = await _target(session, actor, user_id)
    await _lock(session)
    versions = (await _versions(session, [target.id], lock=True))[target.id]
    v = next((o for o in versions if o.id == version_id), None)
    if v is None:
        raise AppError(
            404, ErrorCode.ATTENDANCE_SCHEDULE_VERSION_NOT_FOUND, "Schedule change not found"
        )
    day = today()
    if v.effective_from <= day:
        raise AppError(
            409,
            ErrorCode.ATTENDANCE_SCHEDULE_VERSION_IN_EFFECT,
            "Only upcoming changes can be deleted",
        )
    versions.remove(v)
    await session.delete(v)
    # The version before it now lasts longer: its times must still fit.
    workplace = await _workplace(session, target)
    days = await load_days(session, [workplace], day, day, [target.id])
    days.overrides[target.id] = versions
    _validate_chain(target, days, workplace.id, versions, day)
    audit(
        session,
        "attendance.employee_schedule_version_delete",
        actor_id=actor.id,
        target_user_id=target.id,
        details={
            "user": target.full_name,
            "effective_from": v.effective_from.isoformat(),
            **{f: _shown(f, getattr(v, f)) for f in per.FIELDS},
        },
    )
    await session.commit()


# --- Holiday exceptions --------------------------------------------------------------------------


async def _holiday(session: AsyncSession, holiday_id: uuid.UUID) -> AttendanceHoliday:
    h = await session.get(AttendanceHoliday, holiday_id)
    if h is None:
        raise AppError(404, ErrorCode.ATTENDANCE_HOLIDAY_NOT_FOUND, "Holiday not found")
    return h


async def _exceptions_out(
    session: AsyncSession, viewer: User, h: AttendanceHoliday
) -> list[HolidayExceptionOut]:
    rows = list(
        await session.execute(
            select(AttendanceHolidayException, User)
            .join(User, User.id == AttendanceHolidayException.user_id)
            .where(
                AttendanceHolidayException.holiday_id == h.id,
                User.role.in_(_scope_roles(viewer)),
            )
            .order_by(AttendanceHolidayException.day, func.lower(User.full_name))
        )
    )
    if not rows:
        return []
    workplaces = await active_workplaces(session)
    by_id, default = _effective_workplaces(workplaces)
    days = await load_days(session, workplaces, h.start_date, h.end_date, {u.id for _, u in rows})
    refs = await user_refs(session, {e.created_by for e, _ in rows})
    out = []
    for e, u in rows:
        w = _where(u, by_id, default)
        defs = days.resolve(w.id, e.day, u.id).defs if w else []
        out.append(
            HolidayExceptionOut(
                id=e.id,
                holiday_id=h.id,
                user=UserRef.model_validate(u),
                role=u.role,
                date=e.day,
                shift_codes=e.shift_codes,  # type: ignore[arg-type]
                shift_times=(
                    {c: ShiftTimeOut(**t) for c, t in e.shift_times.items()}  # type: ignore[misc]
                    if e.shift_times
                    else None
                ),
                shifts=_preview_shifts(defs),
                created_by=refs.get(e.created_by) if e.created_by else None,
                created_at=e.created_at,
            )
        )
    return out


async def list_exceptions(
    session: AsyncSession, viewer: User, holiday_id: uuid.UUID
) -> list[HolidayExceptionOut]:
    return await _exceptions_out(session, viewer, await _holiday(session, holiday_id))


def _holiday_payload(h: AttendanceHoliday, day: date) -> dict[str, Any]:
    return {"holiday": h.name_en, "holiday_km": h.name_km, "date": day.isoformat()}


async def set_exceptions(
    session: AsyncSession, actor: User, holiday_id: uuid.UUID, body: HolidayExceptionIn
) -> HolidayExceptionWriteOut:
    await _lock(session)
    h = await _holiday(session, holiday_id)
    day = today()
    dates = sorted(set(body.dates))
    for d in dates:
        if not h.start_date <= d <= h.end_date:
            raise _field_error("dates", "Pick days of this holiday")
        if d < day:
            raise _field_error("dates", "Past days can't be changed")
    targets = await _targets(session, actor, body.user_ids)
    codes = list(body.shift_codes) if body.shift_codes else None
    times = _times_value(body.shift_times)
    existing = {
        (e.user_id, e.day): e
        for e in await session.scalars(
            select(AttendanceHolidayException)
            .where(
                AttendanceHolidayException.holiday_id == h.id,
                AttendanceHolidayException.user_id.in_([u.id for u in targets]),
            )
            .with_for_update()
        )
    }
    written: list[tuple[User, AttendanceHolidayException]] = []
    for u in targets:
        for d in dates:
            e = existing.get((u.id, d))
            if e is not None and e.shift_codes == codes and e.shift_times == times:
                continue
            if e is None:
                e = AttendanceHolidayException(
                    id=uuid.uuid4(),
                    holiday_id=h.id,
                    user_id=u.id,
                    day=d,
                    created_by=actor.id,
                    # The server's clock: set on the day itself, only unopened shifts count.
                    created_at=clock.now(),
                )
                session.add(e)
            e.shift_codes, e.shift_times = codes, times
            written.append((u, e))
    await session.flush()
    for u, e in written:
        workplace = await _workplace(session, u)
        days = await load_days(session, [workplace], e.day, e.day, [u.id])
        if not days.holidays_on(workplace.id, e.day):
            raise _field_error("user_ids", f"{u.full_name} isn't off on this holiday")
        r = days.resolve(workplace.id, e.day, u.id)
        schedule = days.schedule(workplace.id, e.day)
        problems = ovr.defs_problems(per.exception_defs(r.normal, schedule.defs, e), schedule.rules)
        if problems:
            raise ovr.invalid(u, e.day, problems)
        notify_users(
            session,
            HOLIDAY_WORK,
            [u],
            entity_type=ENTITY_HOLIDAY,
            entity_id=h.id,
            payload={
                **_holiday_payload(h, e.day),
                "shifts": _shifts_payload(r.defs),
                "actor_id": str(actor.id),
            },
        )
    if written:
        audit(
            session,
            "attendance.holiday_exception_create",
            actor_id=actor.id,
            entity_type=ENTITY_HOLIDAY,
            entity_id=h.id,
            details={
                "holiday": h.name_en,
                "users": sorted({u.full_name for u, _ in written}),
                "dates": sorted({e.day.isoformat() for _, e in written}),
                "shift_codes": codes,
                "shift_times": _shown("shift_times", times) if times else None,
            },
        )
    await session.commit()
    return HolidayExceptionWriteOut(items=await _exceptions_out(session, actor, h))


async def _remove_records(
    session: AsyncSession, actor: User, user: User, day: date, cause: dict[str, Any]
) -> tuple[int, int]:
    """The day is off for `user` again: their records that day go (corrected ones and locked
    months stay), audited like a holiday's. Returns (removed, skipped_locked)."""
    rows = list(
        await session.scalars(
            select(AttendanceRecord)
            .where(
                AttendanceRecord.user_id == user.id,
                AttendanceRecord.work_date == day,
                AttendanceRecord.corrected.is_(False),
            )
            .order_by(AttendanceRecord.scheduled_start)
            .with_for_update()
        )
    )
    if not rows:
        return 0, 0
    if (user.id, day.year, day.month) in await locked_pairs(session, {user.id}):
        return 0, len(rows)
    await session.execute(
        delete(AttendanceRecord).where(AttendanceRecord.id.in_([r.id for r in rows]))
    )
    audit(
        session,
        "attendance.records_removed_by_day_off",
        actor_id=actor.id,
        target_user_id=user.id,
        details={**cause, "count": len(rows), "records": [_snapshot(r) for r in rows]},
    )
    for r in rows:
        session.expunge(r)
    return len(rows), 0


async def delete_exception(
    session: AsyncSession, actor: User, holiday_id: uuid.UUID, exception_id: uuid.UUID
) -> HolidayExceptionWriteOut:
    await _lock(session)
    h = await _holiday(session, holiday_id)
    e = await session.scalar(
        select(AttendanceHolidayException)
        .where(
            AttendanceHolidayException.id == exception_id,
            AttendanceHolidayException.holiday_id == h.id,
        )
        .with_for_update()
    )
    if e is None:
        raise AppError(404, ErrorCode.ATTENDANCE_EXCEPTION_NOT_FOUND, "Not found")
    target = await _target(session, actor, e.user_id)
    day = today()
    if e.day < day:
        raise _field_error("date", "Past days can't be changed")
    removed = skipped = 0
    if e.day == day:
        removed, skipped = await _remove_records(
            session,
            actor,
            target,
            day,
            {"cause": "attendance.holiday_exception_delete", "holiday": h.name_en},
        )
    audit(
        session,
        "attendance.holiday_exception_delete",
        actor_id=actor.id,
        target_user_id=target.id,
        entity_type=ENTITY_HOLIDAY,
        entity_id=h.id,
        details={
            "holiday": h.name_en,
            "user": target.full_name,
            "date": e.day.isoformat(),
            "records_removed": removed,
        },
    )
    notify_users(
        session,
        HOLIDAY_OFF,
        [target],
        entity_type=ENTITY_HOLIDAY,
        entity_id=h.id,
        payload={**_holiday_payload(h, e.day), "actor_id": str(actor.id)},
    )
    await session.delete(e)
    await session.commit()
    return HolidayExceptionWriteOut(
        items=await _exceptions_out(session, actor, h),
        records_removed=removed,
        skipped_locked=skipped,
    )
