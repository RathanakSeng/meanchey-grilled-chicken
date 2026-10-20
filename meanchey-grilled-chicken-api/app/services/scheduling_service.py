"""Attendance scheduling: schedule versions (tracked weekdays, shifts and rules) per workplace,
holidays, and the calendar.

- **Versions:** a change applies from `effective_from` (today by default, never the past) to one,
  several or all active workplaces, in one transaction. It writes (or replaces) the version on
  that date, copied from the one in effect then, and the same fields of the workplace's later
  upcoming versions, so the change holds from that date on. Upcoming versions can be deleted.
- **Days off** (`app.attendance.days`): a weekday the version doesn't track, or a holiday.
- **Retroactive effects:** every write compares the (workplace, date <= today) pairs that are
  days off before and after it. Pairs newly off lose their records (corrected ones are kept;
  one audit entry holds the removed records' snapshots); pairs back on get their passed
  cutoffs replayed (absents recreated). Writes hold the scheduler's lock so a tick can't
  interleave.
"""

import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from sqlalchemy import and_, delete, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.attendance import clock
from app.attendance import scheduler as sched
from app.attendance import windows as win
from app.attendance.days import DayOff, HolidaySpan, date_range, holidays_between, load_days
from app.attendance.month_lock import locked_pairs
from app.attendance.workplaces import (
    RULE_FIELDS,
    Schedule,
    copy_version,
    default_version,
    shift_def,
    today,
    version_on,
    versions_of,
)
from app.config import get_settings
from app.core.errors import AppError, ErrorCode
from app.models import (
    AttendanceHoliday,
    AttendanceHolidayWorkplace,
    AttendanceRecord,
    AttendanceScheduleVersion,
    AttendanceWorkplace,
    User,
    utcnow,
)
from app.models.attendance import HOLIDAY_MAX_DAYS
from app.schemas.attendance import (
    CalendarDay,
    CalendarOut,
    CalendarWorkplaceDay,
    HolidayBrief,
    HolidayCopyIn,
    HolidayIn,
    HolidayOut,
    SchedulingDiffers,
    SchedulingOut,
    SchedulingWorkplace,
    ShiftsIn,
    Targets,
    UserWorkplace,
    WeekdaysIn,
    WorkplaceOption,
    hm,
)
from app.services.attendance_service import day_off_out, schedule_out, user_refs
from app.services.audit_service import record as audit

SHIFT_POSITIONS = {"morning": 1, "afternoon": 2}
ENTITY_HOLIDAY = "attendance_holiday"


def _field_error(field: str, msg: str) -> AppError:
    return AppError(
        422,
        ErrorCode.VALIDATION_ERROR,
        msg,
        {"fields": [{"loc": ["body", field], "type": "value_error", "msg": msg}]},
    )


async def _lock(session: AsyncSession) -> None:
    """The scheduler's lock: no tick runs between the change and its retroactive effects."""
    await session.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": sched.SCHEDULER_LOCK_KEY})


async def active_workplaces(session: AsyncSession) -> list[AttendanceWorkplace]:
    """Default first, then by name."""
    return list(
        await session.scalars(
            select(AttendanceWorkplace)
            .where(AttendanceWorkplace.is_active)
            .order_by(AttendanceWorkplace.is_default.desc(), func.lower(AttendanceWorkplace.name))
        )
    )


def _not_found() -> AppError:
    return AppError(404, ErrorCode.ATTENDANCE_WORKPLACE_NOT_FOUND, "Workplace not found")


async def _pick(
    session: AsyncSession, ids: Sequence[uuid.UUID] | None
) -> tuple[list[AttendanceWorkplace], list[AttendanceWorkplace]]:
    """(every active workplace, the ones asked for: all when `ids` is None or empty). Unknown →
    404, archived → 409."""
    every = await active_workplaces(session)
    if not ids:
        return every, every
    by_id = {w.id: w for w in every}
    picked = []
    for i in dict.fromkeys(ids):
        if i not in by_id:
            if await session.get(AttendanceWorkplace, i) is not None:
                raise AppError(409, ErrorCode.WORKPLACE_ARCHIVED, "The workplace is archived")
            raise _not_found()
        picked.append(by_id[i])
    order = {w.id: n for n, w in enumerate(every)}
    return every, sorted(picked, key=lambda w: order[w.id])


async def _targets(session: AsyncSession, targets: Targets) -> list[AttendanceWorkplace]:
    _, picked = await _pick(session, None if targets == "all" else targets)  # type: ignore[arg-type]
    return picked


def _effective(value: date | None, day: date) -> date:
    if value is None:
        return day
    if value < day:
        raise _field_error("effective_from", "The date can't be in the past")
    return value


# --- Reading -------------------------------------------------------------------------------------


def _schedule_key(v: AttendanceScheduleVersion) -> tuple:
    return (
        sorted(
            (s["code"], s["start_time"], s["end_time"], s["name_km"], s["name_en"])
            for s in v.shifts
        ),
        tuple(getattr(v, f) for f in RULE_FIELDS),
    )


async def scheduling(
    session: AsyncSession, workplace_ids: Sequence[uuid.UUID] | None
) -> SchedulingOut:
    """The current and upcoming versions of the chosen workplaces (all by default)."""
    day = today()
    every, picked = await _pick(session, workplace_ids)
    versions = await versions_of(session, [w.id for w in picked])
    current = {w.id: version_on(versions[w.id], day) or default_version(w.id, day) for w in picked}
    upcoming = {w.id: [v for v in versions[w.id] if v.effective_from > day] for w in picked}
    refs = await user_refs(
        session,
        {v.created_by for vs in versions.values() for v in vs},
    )
    currents = list(current.values())
    return SchedulingOut(
        today=day,
        timezone=get_settings().business_timezone,
        workplaces=[
            SchedulingWorkplace(
                id=w.id,
                name=w.name,
                is_default=w.is_default,
                current=schedule_out(Schedule(w, current[w.id]), day, refs),
                upcoming=[
                    schedule_out(Schedule(w, v), v.effective_from, refs) for v in upcoming[w.id]
                ],
            )
            for w in picked
        ],
        differs=SchedulingDiffers(
            weekdays=len({tuple(sorted(v.weekdays)) for v in currents}) > 1,
            shifts=len({repr(_schedule_key(v)) for v in currents}) > 1,
        ),
        workplace_options=[
            WorkplaceOption(id=w.id, name=w.name, is_default=w.is_default) for w in every
        ],
    )


def _brief(h: HolidaySpan) -> HolidayBrief:
    return HolidayBrief(id=h.id, name_km=h.name_km, name_en=h.name_en)


async def calendar(
    session: AsyncSession, year: int, month: int, workplace_ids: Sequence[uuid.UUID] | None
) -> CalendarOut:
    """Each day of the month: tracked or not at the chosen workplaces (all by default)."""
    _, picked = await _pick(session, workplace_ids)
    start = date(year, month, 1)
    end = (start + timedelta(days=32)).replace(day=1) - timedelta(days=1)
    days = await load_days(session, picked, start, end)
    out = []
    for d in date_range(start, end):
        offs: list[tuple[uuid.UUID, DayOff | None]] = [
            (w.id, days.day_off(w.id, d)) for w in picked
        ]
        off_count = sum(1 for _, o in offs if o is not None)
        status = "off" if off_count == len(offs) else "tracked" if off_count == 0 else "mixed"
        holidays: dict[uuid.UUID, HolidaySpan] = {}
        for w in picked:
            for h in days.holidays_on(w.id, d):
                holidays.setdefault(h.id, h)
        out.append(
            CalendarDay(
                date=d,
                status=status,  # type: ignore[arg-type]
                day_off=day_off_out(offs[0][1]) if status == "off" and offs else None,
                holidays=[_brief(h) for h in holidays.values()],
                workplaces=[
                    CalendarWorkplaceDay(workplace_id=wid, day_off=day_off_out(o))
                    for wid, o in offs
                ]
                if len(picked) > 1
                else None,
            )
        )
    return CalendarOut(
        year=year,
        month=month,
        today=today(),
        workplaces=[UserWorkplace(id=w.id, name=w.name) for w in picked],
        days=out,
    )


# --- Retroactive effects -------------------------------------------------------------------------


Pairs = set[tuple[uuid.UUID, date]]


@dataclass
class Effects:
    records_removed: int = 0
    absents_recreated: int = 0
    skipped_locked: int = 0  # left alone: the employee's month has a pending / approved request


async def _off_pairs(
    session: AsyncSession, workplaces: Sequence[AttendanceWorkplace], dates: Iterable[date]
) -> Pairs:
    """(workplace, date) pairs that are days off, among dates up to today."""
    day = today()
    dates = sorted({d for d in dates if d <= day})
    if not dates or not workplaces:
        return set()
    await session.flush()
    days = await load_days(session, workplaces, dates[0], dates[-1])
    return days.off_pairs([w.id for w in workplaces], dates)


def _snapshot(r: AttendanceRecord) -> dict[str, Any]:
    def iso(value: Any) -> Any:
        return value.isoformat() if value is not None else None

    return {
        "id": str(r.id),
        "user_id": str(r.user_id),
        "work_date": r.work_date.isoformat(),
        "shift_code": r.shift_code,
        "workplace_id": str(r.workplace_id) if r.workplace_id else None,
        "scheduled_start": iso(r.scheduled_start),
        "scheduled_end": iso(r.scheduled_end),
        "status": r.status,
        "late_minutes": r.late_minutes,
        "early_minutes": r.early_minutes,
        "overtime_minutes": r.overtime_minutes,
        "early_counts": r.early_counts,
        "overtime_counts": r.overtime_counts,
        "check_in_at": iso(r.check_in_at),
        "check_in_lat": str(r.check_in_lat) if r.check_in_lat is not None else None,
        "check_in_lng": str(r.check_in_lng) if r.check_in_lng is not None else None,
        "check_in_accuracy_m": str(r.check_in_accuracy_m)
        if r.check_in_accuracy_m is not None
        else None,
        "check_in_distance_m": str(r.check_in_distance_m)
        if r.check_in_distance_m is not None
        else None,
        "checkout_status": r.checkout_status,
        "check_out_at": iso(r.check_out_at),
        "source": r.source,
    }


async def _apply_effects(
    session: AsyncSession, actor: User, before: Pairs, after: Pairs, cause: dict[str, Any]
) -> Effects:
    effects = Effects()
    newly_off, back_on = after - before, before - after
    if newly_off:
        by_workplace: dict[uuid.UUID, set[date]] = {}
        for wid, d in newly_off:
            by_workplace.setdefault(wid, set()).add(d)
        condition = or_(
            *(
                and_(AttendanceRecord.workplace_id == wid, AttendanceRecord.work_date.in_(dates))
                for wid, dates in by_workplace.items()
            )
        )
        removed = list(
            await session.scalars(
                select(AttendanceRecord)
                .where(condition, AttendanceRecord.corrected.is_(False))
                .order_by(AttendanceRecord.work_date, AttendanceRecord.scheduled_start)
                .with_for_update()
            )
        )
        locked = await locked_pairs(session, {r.user_id for r in removed})
        kept = [r for r in removed if (r.user_id, r.work_date.year, r.work_date.month) in locked]
        effects.skipped_locked += len(kept)
        removed = [r for r in removed if r not in kept]
        if removed:
            await session.execute(
                delete(AttendanceRecord).where(AttendanceRecord.id.in_([r.id for r in removed]))
            )
            audit(
                session,
                "attendance.records_removed_by_day_off",
                actor_id=actor.id,
                details={
                    **cause,
                    "count": len(removed),
                    "records": [_snapshot(r) for r in removed],
                },
            )
            for r in removed:
                session.expunge(r)
        effects.records_removed = len(removed)
    if back_on:
        result = await sched.rerun(session, back_on, clock.now())
        effects.absents_recreated = result.absent
        effects.skipped_locked += result.skipped_locked
    return effects


# --- Versions ------------------------------------------------------------------------------------


def _shown(field: str, value: Any) -> Any:
    if field == "shifts":
        return {
            s["code"]: f"{s['start_time']}–{s['end_time']}"
            for s in sorted(value, key=lambda s: s["position"])
        }
    return value


def _write_version(
    session: AsyncSession,
    actor: User,
    workplace_id: uuid.UUID,
    versions: list[AttendanceScheduleVersion],
    effective_from: date,
    values: dict[str, Any],
) -> dict[str, Any]:
    """Write `values` into the version on `effective_from` (replaced, or a copy of the one in
    effect then) and into the later upcoming versions. Returns the changes (empty: nothing)."""
    same = next((v for v in versions if v.effective_from == effective_from), None)
    source = (
        same
        or version_on(versions, effective_from)
        or default_version(workplace_id, effective_from)
    )
    changes = {
        f: [_shown(f, getattr(source, f)), _shown(f, new)]
        for f, new in values.items()
        if getattr(source, f) != new
    }
    now = utcnow()
    if changes:
        if same is None:
            same = copy_version(source, workplace_id, effective_from, actor.id)
            session.add(same)
        for f, new in values.items():
            setattr(same, f, new)
        same.created_by = actor.id
        same.created_at = now
    later = 0
    for v in versions:
        if v.effective_from > effective_from and any(getattr(v, f) != n for f, n in values.items()):
            for f, new in values.items():
                setattr(v, f, new)
            later += 1
    if later:
        changes["later_versions"] = later
    return changes


async def _write(
    session: AsyncSession,
    actor: User,
    targets: Targets,
    effective_from: date | None,
    values: dict[str, Any],
    action: str,
) -> tuple[list[AttendanceWorkplace], Effects]:
    await _lock(session)
    day = today()
    effective = _effective(effective_from, day)
    workplaces = await _targets(session, targets)
    versions = await versions_of(session, [w.id for w in workplaces], lock=True)
    # Only a change from today can change today (future dates need no cleanup).
    check = [day] if effective == day else []
    before = await _off_pairs(session, workplaces, check)
    changes: dict[str, Any] = {}
    for w in workplaces:
        diff = _write_version(session, actor, w.id, versions[w.id], effective, values)
        if diff:
            changes[w.name] = diff
    after = await _off_pairs(session, workplaces, check)
    effects = Effects()
    if changes:
        effects = await _apply_effects(
            session,
            actor,
            before,
            after,
            {"cause": action, "effective_from": effective.isoformat()},
        )
        audit(
            session,
            action,
            actor_id=actor.id,
            details={
                "workplaces": [w.name for w in workplaces],
                "all_workplaces": targets == "all",
                "effective_from": effective.isoformat(),
                "changes": changes,
                "records_removed": effects.records_removed,
                "absents_recreated": effects.absents_recreated,
            },
        )
    await session.commit()
    return workplaces, effects


async def set_weekdays(
    session: AsyncSession, actor: User, body: WeekdaysIn
) -> tuple[list[AttendanceWorkplace], Effects]:
    return await _write(
        session,
        actor,
        body.workplace_ids,
        body.effective_from,
        {"weekdays": body.weekdays},
        "attendance.weekdays_update",
    )


def _validate(defs: list[win.ShiftDef], rules: win.Rules) -> None:
    problems = win.validate(defs, rules)
    if problems:
        raise AppError(
            422,
            ErrorCode.VALIDATION_ERROR,
            problems[0][1],
            {"fields": [{"loc": loc, "type": "value_error", "msg": msg} for loc, msg in problems]},
        )


async def set_shifts(
    session: AsyncSession, actor: User, body: ShiftsIn
) -> tuple[list[AttendanceWorkplace], Effects]:
    """Both shifts and the rules, validated as one day. Records already made keep their
    snapshots; from today, the new times apply to windows that haven't opened yet."""
    shifts = sorted(
        (
            {
                "code": x.code,
                "name_km": x.name_km,
                "name_en": x.name_en,
                "start_time": hm(x.start_time),
                "end_time": hm(x.end_time),
                "position": SHIFT_POSITIONS[x.code],
            }
            for x in body.shifts
        ),
        key=lambda s: s["position"],
    )
    rules = {f: getattr(body, f) for f in RULE_FIELDS}
    _validate([shift_def(s) for s in shifts], win.Rules(**rules))
    return await _write(
        session,
        actor,
        body.workplace_ids,
        body.effective_from,
        {"shifts": shifts, **rules},
        "attendance.schedule_update",
    )


async def delete_version(session: AsyncSession, actor: User, version_id: uuid.UUID) -> None:
    """Only an upcoming version (effective after today)."""
    v = await session.scalar(
        select(AttendanceScheduleVersion)
        .where(AttendanceScheduleVersion.id == version_id)
        .with_for_update()
    )
    if v is None:
        raise AppError(
            404, ErrorCode.ATTENDANCE_SCHEDULE_VERSION_NOT_FOUND, "Schedule change not found"
        )
    if v.effective_from <= today():
        raise AppError(
            409,
            ErrorCode.ATTENDANCE_SCHEDULE_VERSION_IN_EFFECT,
            "Only upcoming changes can be deleted",
        )
    workplace = await session.get(AttendanceWorkplace, v.workplace_id)
    audit(
        session,
        "attendance.schedule_version_delete",
        actor_id=actor.id,
        details={
            "workplace": workplace.name if workplace else None,
            "effective_from": v.effective_from.isoformat(),
            "weekdays": sorted(v.weekdays),
            "shifts": _shown("shifts", v.shifts),
            **{f: getattr(v, f) for f in RULE_FIELDS},
        },
    )
    await session.delete(v)
    await session.commit()


# --- Holidays ------------------------------------------------------------------------------------


async def _links(session: AsyncSession, ids: list[uuid.UUID]) -> dict[uuid.UUID, list[uuid.UUID]]:
    out: dict[uuid.UUID, list[uuid.UUID]] = {i: [] for i in ids}
    if ids:
        for hid, wid in await session.execute(
            select(
                AttendanceHolidayWorkplace.holiday_id, AttendanceHolidayWorkplace.workplace_id
            ).where(AttendanceHolidayWorkplace.holiday_id.in_(ids))
        ):
            out[hid].append(wid)
    return out


async def holidays_out(
    session: AsyncSession, holidays: list[AttendanceHoliday]
) -> list[HolidayOut]:
    links = await _links(session, [h.id for h in holidays])
    workplace_ids = {w for ws in links.values() for w in ws}
    names = (
        {
            w.id: w
            for w in await session.scalars(
                select(AttendanceWorkplace).where(AttendanceWorkplace.id.in_(workplace_ids))
            )
        }
        if workplace_ids
        else {}
    )
    refs = await user_refs(session, {x for h in holidays for x in (h.created_by, h.updated_by)})
    out = []
    for h in holidays:
        linked = sorted(
            (names[w] for w in links[h.id] if w in names),
            key=lambda w: (not w.is_default, w.name.casefold()),
        )
        out.append(
            HolidayOut(
                id=h.id,
                name_km=h.name_km,
                name_en=h.name_en,
                start_date=h.start_date,
                end_date=h.end_date,
                days=(h.end_date - h.start_date).days + 1,
                scope=h.scope,  # type: ignore[arg-type]
                workplaces=[UserWorkplace(id=w.id, name=w.name) for w in linked],
                note=h.note,
                created_by=refs.get(h.created_by) if h.created_by else None,
                created_at=h.created_at,
                updated_by=refs.get(h.updated_by) if h.updated_by else None,
                updated_at=h.updated_at,
            )
        )
    return out


async def holiday_out(session: AsyncSession, h: AttendanceHoliday) -> HolidayOut:
    (out,) = await holidays_out(session, [h])
    return out


async def list_holidays(
    session: AsyncSession, year: int | None, workplace_id: uuid.UUID | None
) -> list[HolidayOut]:
    """Holidays overlapping the year (default this year), optionally those covering one
    workplace."""
    year = year or today().year
    spans = await holidays_between(session, date(year, 1, 1), date(year, 12, 31))
    if workplace_id is not None:
        spans = [h for h in spans if h.scope == "all" or workplace_id in h.workplace_ids]
    if not spans:
        return []
    rows = {
        h.id: h
        for h in await session.scalars(
            select(AttendanceHoliday).where(AttendanceHoliday.id.in_([s.id for s in spans]))
        )
    }
    return await holidays_out(session, [rows[s.id] for s in spans])


async def get_holiday(
    session: AsyncSession, holiday_id: uuid.UUID, *, lock: bool = False
) -> AttendanceHoliday:
    stmt = select(AttendanceHoliday).where(AttendanceHoliday.id == holiday_id)
    if lock:
        stmt = stmt.with_for_update()
    h = await session.scalar(stmt)
    if h is None:
        raise AppError(404, ErrorCode.ATTENDANCE_HOLIDAY_NOT_FOUND, "Holiday not found")
    return h


async def _check_holiday(
    session: AsyncSession, body: HolidayIn
) -> list[AttendanceWorkplace] | None:
    """The selected workplaces (None for `all`)."""
    if body.end_date < body.start_date:
        raise _field_error("end_date", "The holiday must end on or after its first day")
    if (body.end_date - body.start_date).days + 1 > HOLIDAY_MAX_DAYS:
        raise _field_error("end_date", f"A holiday is at most {HOLIDAY_MAX_DAYS} days")
    for field in ("start_date", "end_date"):
        if not 2000 <= getattr(body, field).year <= 2100:
            raise _field_error(field, "The year must be between 2000 and 2100")
    if body.scope == "all":
        return None
    if not body.workplace_ids:
        raise _field_error("workplace_ids", "Choose at least one workplace")
    _, picked = await _pick(session, body.workplace_ids)
    return picked


def _affected(
    every: list[AttendanceWorkplace], scope: str, ids: Iterable[uuid.UUID]
) -> list[AttendanceWorkplace]:
    if scope == "all":
        return every
    wanted = set(ids)
    return [w for w in every if w.id in wanted]


def _state(h: AttendanceHoliday, workplaces: list[str]) -> dict[str, Any]:
    return {
        "name_km": h.name_km,
        "name_en": h.name_en,
        "start_date": h.start_date.isoformat(),
        "end_date": h.end_date.isoformat(),
        "scope": h.scope,
        "workplaces": workplaces,
        "note": h.note,
    }


async def create_holiday(
    session: AsyncSession, actor: User, body: HolidayIn
) -> tuple[AttendanceHoliday, Effects]:
    selected = await _check_holiday(session, body)
    await _lock(session)
    every = await active_workplaces(session)
    affected = every if selected is None else selected
    dates = date_range(body.start_date, body.end_date)
    before = await _off_pairs(session, affected, dates)
    now = utcnow()
    h = AttendanceHoliday(
        name_km=body.name_km,
        name_en=body.name_en,
        start_date=body.start_date,
        end_date=body.end_date,
        scope=body.scope,
        note=body.note,
        created_by=actor.id,
        updated_by=actor.id,
        created_at=now,
        updated_at=now,
    )
    session.add(h)
    await session.flush()
    for w in selected or []:
        session.add(AttendanceHolidayWorkplace(holiday_id=h.id, workplace_id=w.id))
    after = await _off_pairs(session, affected, dates)
    effects = await _apply_effects(
        session,
        actor,
        before,
        after,
        {"cause": "attendance.holiday_create", "holiday_id": str(h.id), "holiday": h.name_en},
    )
    audit(
        session,
        "attendance.holiday_create",
        actor_id=actor.id,
        entity_type=ENTITY_HOLIDAY,
        entity_id=h.id,
        details={
            **_state(h, [w.name for w in selected or []]),
            "records_removed": effects.records_removed,
        },
    )
    await session.commit()
    await session.refresh(h)
    return h, effects


async def update_holiday(
    session: AsyncSession, actor: User, holiday_id: uuid.UUID, body: HolidayIn
) -> tuple[AttendanceHoliday, Effects]:
    selected = await _check_holiday(session, body)
    await _lock(session)
    h = await get_holiday(session, holiday_id, lock=True)
    old_links = (await _links(session, [h.id]))[h.id]
    every = await active_workplaces(session)
    names = {w.id: w.name for w in every}
    before_state = _state(h, [names[w] for w in old_links if w in names])
    affected = {
        w.id: w
        for w in [
            *_affected(every, h.scope, old_links),
            *(every if selected is None else selected),
        ]
    }
    dates = {*date_range(h.start_date, h.end_date), *date_range(body.start_date, body.end_date)}
    before = await _off_pairs(session, list(affected.values()), dates)
    h.name_km, h.name_en, h.note = body.name_km, body.name_en, body.note
    h.start_date, h.end_date, h.scope = body.start_date, body.end_date, body.scope
    new_links = [w.id for w in selected or []]
    if set(new_links) != set(old_links):
        await session.execute(
            delete(AttendanceHolidayWorkplace).where(AttendanceHolidayWorkplace.holiday_id == h.id)
        )
        for wid in new_links:
            session.add(AttendanceHolidayWorkplace(holiday_id=h.id, workplace_id=wid))
    after_state = _state(h, [w.name for w in selected or []])
    if after_state == before_state:
        await session.rollback()
        return await get_holiday(session, holiday_id), Effects()
    h.updated_by = actor.id
    h.updated_at = utcnow()
    after = await _off_pairs(session, list(affected.values()), dates)
    effects = await _apply_effects(
        session,
        actor,
        before,
        after,
        {"cause": "attendance.holiday_update", "holiday_id": str(h.id), "holiday": h.name_en},
    )
    audit(
        session,
        "attendance.holiday_update",
        actor_id=actor.id,
        entity_type=ENTITY_HOLIDAY,
        entity_id=h.id,
        details={
            "before": before_state,
            "after": after_state,
            "records_removed": effects.records_removed,
            "absents_recreated": effects.absents_recreated,
        },
    )
    await session.commit()
    await session.refresh(h)
    return h, effects


async def delete_holiday(session: AsyncSession, actor: User, holiday_id: uuid.UUID) -> Effects:
    await _lock(session)
    h = await get_holiday(session, holiday_id, lock=True)
    links = (await _links(session, [h.id]))[h.id]
    every = await active_workplaces(session)
    names = {w.id: w.name for w in every}
    affected = _affected(every, h.scope, links)
    dates = date_range(h.start_date, h.end_date)
    before = await _off_pairs(session, affected, dates)
    state = _state(h, [names[w] for w in links if w in names])
    await session.delete(h)
    await session.flush()
    after = await _off_pairs(session, affected, dates)
    effects = await _apply_effects(
        session,
        actor,
        before,
        after,
        {"cause": "attendance.holiday_delete", "holiday_id": str(holiday_id)},
    )
    audit(
        session,
        "attendance.holiday_delete",
        actor_id=actor.id,
        entity_type=ENTITY_HOLIDAY,
        entity_id=holiday_id,
        details={**state, "absents_recreated": effects.absents_recreated},
    )
    await session.commit()
    return effects


def _move_year(d: date, years: int) -> date:
    """The same month / day `years` later (Feb 29 → Feb 28 when that year has none)."""
    try:
        return d.replace(year=d.year + years)
    except ValueError:
        return d.replace(year=d.year + years, day=28)


async def copy_holidays(
    session: AsyncSession, actor: User, body: HolidayCopyIn
) -> tuple[list[AttendanceHoliday], int, Effects]:
    """Every holiday starting in `from_year`, on the same month / day in `to_year`, same names,
    scope and workplaces. One that would duplicate a holiday with the same name and dates is
    skipped. Returns (created, skipped, effects)."""
    if body.from_year == body.to_year:
        raise _field_error("to_year", "Choose another year")
    await _lock(session)
    years = body.to_year - body.from_year
    source = list(
        await session.scalars(
            select(AttendanceHoliday)
            .where(func.extract("year", AttendanceHoliday.start_date) == body.from_year)
            .order_by(AttendanceHoliday.start_date, AttendanceHoliday.name_en)
        )
    )
    links = await _links(session, [h.id for h in source])
    every = await active_workplaces(session)
    planned = []
    for h in source:
        start, end = _move_year(h.start_date, years), _move_year(h.end_date, years)
        planned.append((h, start, end))
    if not planned:
        await session.rollback()
        return [], 0, Effects()
    existing = list(
        await session.scalars(
            select(AttendanceHoliday).where(
                AttendanceHoliday.start_date <= max(e for _, _, e in planned),
                AttendanceHoliday.end_date >= min(s for _, s, _ in planned),
            )
        )
    )

    def duplicate(h: AttendanceHoliday, start: date, end: date) -> bool:
        return any(
            x.start_date == start
            and x.end_date == end
            and (
                x.name_en.casefold() == h.name_en.casefold()
                or x.name_km.casefold() == h.name_km.casefold()
            )
            for x in existing
        )

    todo = [(h, s, e) for h, s, e in planned if not duplicate(h, s, e)]
    affected: dict[uuid.UUID, AttendanceWorkplace] = {}
    dates: set[date] = set()
    for h, s, e in todo:
        affected.update({w.id: w for w in _affected(every, h.scope, links[h.id])})
        dates.update(date_range(s, e))
    before = await _off_pairs(session, list(affected.values()), dates)
    now = utcnow()
    created = []
    for h, s, e in todo:
        new = AttendanceHoliday(
            name_km=h.name_km,
            name_en=h.name_en,
            start_date=s,
            end_date=e,
            scope=h.scope,
            note=h.note,
            created_by=actor.id,
            updated_by=actor.id,
            created_at=now,
            updated_at=now,
        )
        session.add(new)
        await session.flush()
        for wid in links[h.id]:
            session.add(AttendanceHolidayWorkplace(holiday_id=new.id, workplace_id=wid))
        created.append(new)
    after = await _off_pairs(session, list(affected.values()), dates)
    effects = await _apply_effects(
        session,
        actor,
        before,
        after,
        {"cause": "attendance.holiday_copy", "to_year": body.to_year},
    )
    audit(
        session,
        "attendance.holiday_copy",
        actor_id=actor.id,
        details={
            "from_year": body.from_year,
            "to_year": body.to_year,
            "created": [
                {
                    "name_en": h.name_en,
                    "start_date": h.start_date.isoformat(),
                    "end_date": h.end_date.isoformat(),
                }
                for h in created
            ],
            "skipped": len(planned) - len(todo),
            "records_removed": effects.records_removed,
        },
    )
    await session.commit()
    for h in created:
        await session.refresh(h)
    return created, len(planned) - len(todo), effects
