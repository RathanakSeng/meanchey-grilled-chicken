"""Attendance: today's state, check-in / check-out, the day view, corrections, workplaces and
the summaries. Scheduling (versions, weekdays, holidays) is in `scheduling_service`.

- **Tracked employees** are the active staff and supervisors (never the general manager or the
  superadmin). Each is assigned to one workplace; **each workplace has its own schedule per
  date** (a version: tracked weekdays, two shifts and the window rules), so windows are evaluated
  per workplace and date. **Days off** (an untracked weekday or a holiday) have no windows.
- **Time comes from the server** (`app.attendance.clock`, BUSINESS_TIMEZONE), the location from
  the phone's GPS inside the Mini App. The server picks the shift; the windows and rules are pure
  functions in `app.attendance.windows`.
- **Refused attempts** are audited (`attendance.attempt_refused`, committed before the error is
  raised, like the lockout); no record is created.
- **Records snapshot the shift times**, so later changes never rewrite history.
"""

import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import and_, delete, false, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.attendance import clock
from app.attendance import requests as req
from app.attendance import summary as summ
from app.attendance import windows as win
from app.attendance.days import LOOKAHEAD_DAYS, DayOff, Days, load_days
from app.attendance.month_lock import LOCKING, ensure_unlocked
from app.attendance.request_settings import get_deadline_day
from app.attendance.tracking import in_period, status_on
from app.attendance.workplaces import (
    DEFAULT_SHIFTS,
    RULE_FIELDS,
    TRACKED_ROLES,
    Schedule,
    copy_version,
    default_version,
    default_workplace,
    is_tracked,
    user_workplace,
    version_on,
    versions_of,
)
from app.config import get_settings
from app.core.errors import AppError, ErrorCode
from app.models import (
    AttendanceRecord,
    AttendanceRequest,
    AttendanceScheduleVersion,
    AttendanceWorkplace,
    Role,
    User,
    utcnow,
)
from app.models.attendance import CHECKOUT_WINDOW_MAX, OPEN_BEFORE_MAX, SHIFT_CODES
from app.permissions.hierarchy import MANAGEABLE_ROLES, ensure_can_manage
from app.schemas.attendance import (
    CorrectionIn,
    DayCell,
    DayOffOut,
    DayOut,
    DayRow,
    DayShiftOut,
    DayWorkplaceOut,
    HolidayBrief,
    LocationIn,
    MeTodayOut,
    NextActionOut,
    RecordCreateIn,
    RecordOut,
    ScheduleOut,
    ShiftDayOut,
    ShiftKpis,
    ShiftOut,
    ShiftWindowsOut,
    SummaryCount,
    SummaryDay,
    SummaryDayShift,
    SummaryEmployee,
    SummaryKpis,
    SummaryOut,
    SummaryPeriod,
    SummaryShift,
    SummaryShifts,
    UserWorkplace,
    WorkplaceBrief,
    WorkplaceCreate,
    WorkplaceEmployee,
    WorkplaceOut,
    WorkplaceUpdate,
)
from app.schemas.attendance_request import RequestBrief
from app.schemas.common import UserRef
from app.services.audit_service import record as audit
from app.services.user_service import get_user_or_404

ENTITY_RECORD = "attendance_record"
ENTITY_WORKPLACE = "attendance_workplace"


def tz() -> ZoneInfo:
    return get_settings().business_tz


def _default_values(workplace_id: uuid.UUID, day: date) -> dict[str, Any]:
    v = default_version(workplace_id, day)
    return {
        "workplace_id": workplace_id,
        "effective_from": day,
        **{f: getattr(v, f) for f in ("weekdays", "shifts", *RULE_FIELDS)},
    }


# --- Schedules ----------------------------------------------------------------------------------


async def user_days(
    session: AsyncSession, user: User, start: date, end: date
) -> tuple[AttendanceWorkplace, Days] | None:
    """The workplace where `user` checks in and its days over [start, end] (None only without
    any workplace)."""
    workplace = await user_workplace(session, user)
    if workplace is None:
        return None
    return workplace, await load_days(session, [workplace], start, end)


def day_off_out(off: DayOff | None) -> DayOffOut | None:
    if off is None:
        return None
    return DayOffOut(
        reason=off.reason,
        holidays=[
            HolidayBrief(id=h.id, name_km=h.name_km, name_en=h.name_en) for h in off.holidays
        ],
    )


# --- Serialization -------------------------------------------------------------------------------


def _local(value: datetime | None) -> datetime | None:
    return value.astimezone(tz()) if value is not None else None


def _float(value: Decimal | None) -> float | None:
    return float(value) if value is not None else None


async def user_refs(session: AsyncSession, ids: set[uuid.UUID | None]) -> dict[uuid.UUID, UserRef]:
    wanted = {i for i in ids if i is not None}
    if not wanted:
        return {}
    users = await session.scalars(select(User).where(User.id.in_(wanted)))
    return {u.id: UserRef.model_validate(u) for u in users}


def request_brief_out(r: AttendanceRequest, refs: dict[uuid.UUID, UserRef]) -> RequestBrief:
    return RequestBrief(
        id=r.id,
        status=r.status,  # type: ignore[arg-type]
        type=r.type,  # type: ignore[arg-type]
        requested_salary_cut_minutes=r.requested_salary_cut_minutes,
        requested_unpaid_work_minutes=r.requested_unpaid_work_minutes,
        approved_salary_cut_minutes=r.approved_salary_cut_minutes,
        approved_unpaid_work_minutes=r.approved_unpaid_work_minutes,
        approved_with_changes=r.approved_with_changes,
        review_comment=r.review_comment,
        reject_reason=r.reject_reason,
        submitted_at=r.submitted_at,
        reviewed_by=refs.get(r.reviewed_by) if r.reviewed_by else None,
        reviewed_at=r.reviewed_at,
    )


def record_out(r: AttendanceRecord, refs: dict[uuid.UUID, UserRef]) -> RecordOut:
    return RecordOut(
        id=r.id,
        user_id=r.user_id,
        work_date=r.work_date,
        shift_code=r.shift_code,  # type: ignore[arg-type]
        workplace_id=r.workplace_id,
        scheduled_start=_local(r.scheduled_start),  # type: ignore[arg-type]
        scheduled_end=_local(r.scheduled_end),  # type: ignore[arg-type]
        status=r.status,  # type: ignore[arg-type]
        late_minutes=r.late_minutes,
        early_minutes=r.early_minutes,
        overtime_minutes=r.overtime_minutes,
        early_counts=r.early_counts,
        overtime_counts=r.overtime_counts,
        check_in_at=_local(r.check_in_at),
        check_in_distance_m=_float(r.check_in_distance_m),
        check_in_accuracy_m=_float(r.check_in_accuracy_m),
        checkout_status=r.checkout_status,  # type: ignore[arg-type]
        check_out_at=_local(r.check_out_at),
        check_out_distance_m=_float(r.check_out_distance_m),
        check_out_accuracy_m=_float(r.check_out_accuracy_m),
        source=r.source,  # type: ignore[arg-type]
        corrected=r.corrected,
        correction_reason=r.correction_reason,
        corrected_by=refs.get(r.corrected_by) if r.corrected_by else None,
        corrected_at=_local(r.corrected_at),
    )


async def records_out(session: AsyncSession, records: list[AttendanceRecord]) -> list[RecordOut]:
    refs = await user_refs(session, {r.corrected_by for r in records})
    return [record_out(r, refs) for r in records]


def phase(w: win.ShiftWindows, now: datetime) -> str:
    if now < w.check_in_opens:
        return "upcoming"
    if now < w.check_in_closes:
        return "check_in_open"
    if now < w.check_out_opens:
        return "in_progress"
    if now < w.check_out_closes:
        return "check_out_open"
    return "closed"


def workplace_brief(w: AttendanceWorkplace | None) -> WorkplaceBrief | None:
    if w is None:
        return None
    return WorkplaceBrief(
        id=w.id,
        name=w.name,
        address=w.address,
        latitude=_float(w.latitude),
        longitude=_float(w.longitude),
        radius_m=w.radius_m,
        has_coordinates=w.has_coordinates,
    )


def _iso(value: datetime | None) -> str | None:
    return value.astimezone(tz()).isoformat() if value is not None else None


def _next_action_out(na: win.NextAction) -> NextActionOut:
    return NextActionOut(
        action=na.action,
        shift_code=na.window.code if na.window else None,  # type: ignore[arg-type]
        until=_local(win.shown_until(na.until)) if na.until else None,
        closes_at=_local(na.until),
        next_action=na.next_action,
        next_shift_code=na.next_window.code if na.next_window else None,  # type: ignore[arg-type]
        next_opens_at=_local(na.next_opens_at),
    )


# --- Today's state -------------------------------------------------------------------------------


def _not_required() -> AppError:
    return AppError(
        403, ErrorCode.ATTENDANCE_NOT_REQUIRED, "Attendance isn't recorded for this account"
    )


async def _records_of(
    session: AsyncSession, user_id: uuid.UUID, day: date
) -> dict[str, AttendanceRecord]:
    rows = await session.scalars(
        select(AttendanceRecord).where(
            AttendanceRecord.user_id == user_id, AttendanceRecord.work_date == day
        )
    )
    return {r.shift_code: r for r in rows}


async def me_today(session: AsyncSession, user: User, now: datetime | None = None) -> MeTodayOut:
    if not is_tracked(user):
        raise _not_required()
    now = now or clock.now()
    day = win.work_date(now, tz())
    status = status_on(user, day, user.attendance_periods)
    if status in ("not_started", "untracked"):
        # Nothing to do (yet / any more): the Mini App shows when it starts or that it isn't
        # required.
        return MeTodayOut(
            server_time=_local(now),  # type: ignore[arg-type]
            timezone=get_settings().business_timezone,
            work_date=day,
            workplace=workplace_brief(await user_workplace(session, user)),
            max_accuracy_m=0,
            day_off=None,
            shifts=[],
            next_action=NextActionOut(action="none"),
            tracked=status != "untracked",
            starts_on=user.attendance_start_date if status == "not_started" else None,
        )
    found = await user_days(session, user, day, day + timedelta(days=LOOKAHEAD_DAYS))
    workplace, days = found if found else (None, None)
    off = days.day_off(workplace.id, day) if days and workplace else None
    today = days.windows(workplace.id, day) if days and workplace else []
    upcoming = days.next_tracked(workplace.id, day) if days and workplace else []
    records = await _records_of(session, user.id, day) if off is None else {}
    refs = await user_refs(session, {r.corrected_by for r in records.values()})
    shifts = [
        ShiftDayOut(
            code=w.code,  # type: ignore[arg-type]
            name_km=w.shift.name_km,
            name_en=w.shift.name_en,
            start=_local(w.start),  # type: ignore[arg-type]
            end=_local(w.end),  # type: ignore[arg-type]
            check_in_opens=_local(w.check_in_opens),  # type: ignore[arg-type]
            check_in_until=_local(win.shown_until(w.check_in_closes)),  # type: ignore[arg-type]
            check_out_opens=_local(w.check_out_opens),  # type: ignore[arg-type]
            check_out_until=_local(win.shown_until(w.check_out_closes)),  # type: ignore[arg-type]
            phase=phase(w, now),  # type: ignore[arg-type]
            record=record_out(records[w.code], refs) if w.code in records else None,
        )
        for w in today
    ]
    return MeTodayOut(
        server_time=_local(now),  # type: ignore[arg-type]
        timezone=get_settings().business_timezone,
        work_date=day,
        workplace=workplace_brief(workplace),
        max_accuracy_m=days.schedule(workplace.id, day).rules.max_accuracy_m
        if days and workplace
        else 0,
        day_off=day_off_out(off),
        shifts=shifts,
        next_action=_next_action_out(win.next_action(today, upcoming, records, now)),
    )


# --- Check-in / check-out ------------------------------------------------------------------------


@dataclass
class _Attempt:
    action: str
    location: LocationIn
    shift_code: str | None = None
    distance_m: float | None = None


async def _refuse(
    session: AsyncSession,
    user_id: uuid.UUID,
    attempt: _Attempt,
    status: int,
    code: ErrorCode,
    message: str,
    details: dict[str, Any] | None = None,
) -> AppError:
    """Audit the refused attempt (committed: the error rolls nothing back) and return the error."""
    audit(
        session,
        "attendance.attempt_refused",
        actor_id=user_id,
        target_user_id=user_id,
        details={
            "action": attempt.action,
            "code": code.value,
            "shift": attempt.shift_code,
            "distance_m": round(attempt.distance_m) if attempt.distance_m is not None else None,
            "accuracy_m": round(attempt.location.accuracy_m, 1),
        },
    )
    await session.commit()
    return AppError(status, code, message, details)


def _q(value: float, places: str) -> Decimal:
    return Decimal(str(value)).quantize(Decimal(places))


async def check(
    session: AsyncSession, user: User, action: str, location: LocationIn
) -> AttendanceRecord:
    """Record a check-in or check-out now. Checks, in order: tracked, workplace set, time window,
    duplicates / order, GPS accuracy, distance. Commits."""
    attempt = _Attempt(action, location)
    user_id = user.id
    if not is_tracked(user):
        raise await _refuse(
            session,
            user_id,
            attempt,
            403,
            ErrorCode.ATTENDANCE_NOT_REQUIRED,
            "Attendance isn't recorded for this account",
        )
    now = clock.now()
    day = win.work_date(now, tz())
    status = status_on(user, day, user.attendance_periods)
    if status == "untracked":
        raise await _refuse(
            session,
            user_id,
            attempt,
            403,
            ErrorCode.ATTENDANCE_NOT_REQUIRED,
            "Attendance isn't required for this account",
        )
    if status == "not_started":
        assert user.attendance_start_date is not None
        raise await _refuse(
            session,
            user_id,
            attempt,
            409,
            ErrorCode.ATTENDANCE_NOT_STARTED,
            "Attendance hasn't started yet",
            {"start_date": user.attendance_start_date.isoformat()},
        )
    workplace = await user_workplace(session, user)
    if workplace is None or not workplace.has_coordinates:
        raise await _refuse(
            session,
            user_id,
            attempt,
            409,
            ErrorCode.ATTENDANCE_WORKPLACE_NOT_SET,
            "The workplace's position isn't set yet",
        )
    assert workplace.latitude is not None and workplace.longitude is not None
    attempt.distance_m = win.haversine_m(
        float(workplace.latitude), float(workplace.longitude), location.latitude, location.longitude
    )

    days = await load_days(session, [workplace], day, day + timedelta(days=LOOKAHEAD_DAYS))
    schedule = days.schedule(workplace.id, day)
    today = days.windows(workplace.id, day)
    tomorrow = days.next_tracked(workplace.id, day)
    off = days.day_off(workplace.id, day)
    if off is not None:
        nxt = tomorrow[0] if tomorrow else None
        raise await _refuse(
            session,
            user_id,
            attempt,
            409,
            ErrorCode.ATTENDANCE_DAY_OFF,
            "Today is a day off",
            {
                "reason": off.reason,
                "holidays": [{"name_km": h.name_km, "name_en": h.name_en} for h in off.holidays],
                "next_opens_at": _iso(nxt.check_in_opens) if nxt else None,
                "next_shift_code": nxt.code if nxt else None,
            },
        )

    if action == "check_in":
        decision = win.decide_check_in(today, tomorrow, now)
        nxt = decision.next_window
        next_details = {
            "next_opens_at": _iso(nxt.check_in_opens) if nxt else None,
            "next_shift_code": nxt.code if nxt else None,
        }
        if decision.kind == "too_early":
            raise await _refuse(
                session,
                user_id,
                attempt,
                409,
                ErrorCode.ATTENDANCE_TOO_EARLY,
                "Check-in isn't open yet",
                {
                    "opens_at": next_details["next_opens_at"],
                    "shift_code": next_details["next_shift_code"],
                },
            )
        if decision.kind == "no_shift":
            raise await _refuse(
                session,
                user_id,
                attempt,
                409,
                ErrorCode.ATTENDANCE_NO_SHIFT_NOW,
                "No shift to check in to now",
                next_details,
            )
        assert decision.window is not None
        attempt.shift_code = decision.window.code
        if decision.kind == "closed":
            raise await _refuse(
                session,
                user_id,
                attempt,
                409,
                ErrorCode.ATTENDANCE_CHECKIN_CLOSED,
                "Check-in for this shift is closed",
                {
                    "shift_code": decision.window.code,
                    "closed_at": _iso(decision.window.check_in_closes),
                    **next_details,
                },
            )
        w = decision.window
    else:
        out = win.decide_check_out(today, now)
        assert out is not None
        w = out.window
        attempt.shift_code = w.code
        if out.kind == "too_early":
            raise await _refuse(
                session,
                user_id,
                attempt,
                409,
                ErrorCode.ATTENDANCE_CHECKOUT_TOO_EARLY,
                "Check-out isn't open yet",
                {"opens_at": _iso(w.check_out_opens), "shift_code": w.code},
            )
        if out.kind == "closed":
            raise await _refuse(
                session,
                user_id,
                attempt,
                409,
                ErrorCode.ATTENDANCE_CHECKOUT_CLOSED,
                "Check-out for this shift is closed",
                {"shift_code": w.code, "closed_at": _iso(w.check_out_closes)},
            )

    record = await session.scalar(
        select(AttendanceRecord)
        .where(
            AttendanceRecord.user_id == user.id,
            AttendanceRecord.work_date == day,
            AttendanceRecord.shift_code == w.code,
        )
        .with_for_update()
    )
    if action == "check_in" and record is not None:
        raise await _refuse(
            session,
            user_id,
            attempt,
            409,
            ErrorCode.ATTENDANCE_ALREADY_CHECKED_IN,
            "Already checked in to this shift",
            {"shift_code": w.code},
        )
    if action == "check_out":
        if record is None or record.status == "absent" or record.check_in_at is None:
            raise await _refuse(
                session,
                user_id,
                attempt,
                409,
                ErrorCode.ATTENDANCE_NOT_CHECKED_IN,
                "Not checked in to this shift",
                {"shift_code": w.code},
            )
        if record.checkout_status is not None:
            raise await _refuse(
                session,
                user_id,
                attempt,
                409,
                ErrorCode.ATTENDANCE_ALREADY_CHECKED_OUT,
                "Already checked out of this shift",
                {"shift_code": w.code},
            )

    max_accuracy = schedule.rules.max_accuracy_m
    if location.accuracy_m > max_accuracy:
        raise await _refuse(
            session,
            user_id,
            attempt,
            422,
            ErrorCode.ATTENDANCE_LOCATION_INACCURATE,
            "The GPS position isn't accurate enough",
            {"accuracy_m": round(location.accuracy_m), "max": max_accuracy},
        )
    if attempt.distance_m > workplace.radius_m:
        raise await _refuse(
            session,
            user_id,
            attempt,
            422,
            ErrorCode.ATTENDANCE_TOO_FAR,
            "Too far from the workplace",
            {"distance_m": round(attempt.distance_m), "radius_m": workplace.radius_m},
        )

    lat, lng = _q(location.latitude, "0.000001"), _q(location.longitude, "0.000001")
    accuracy, distance = _q(location.accuracy_m, "0.1"), _q(attempt.distance_m, "0.1")
    stamp = now.replace(microsecond=0)
    rules = schedule.rules
    if action == "check_in":
        late = win.late_minutes(stamp, w.start)
        record = AttendanceRecord(
            user_id=user.id,
            work_date=day,
            shift_code=w.code,
            workplace_id=workplace.id,
            scheduled_start=w.start,
            scheduled_end=w.end,
            status="late" if late else "present",
            late_minutes=late,
            # The workplace's flags are snapshotted: a later settings change keeps this record.
            early_counts=rules.count_early_checkin,
            overtime_counts=rules.count_overtime,
            early_minutes=win.early_minutes(stamp, w.start, rules.open_before_min)
            if rules.count_early_checkin
            else 0,
            check_in_at=stamp,
            check_in_lat=lat,
            check_in_lng=lng,
            check_in_accuracy_m=accuracy,
            check_in_distance_m=distance,
            source="mini_app",
        )
        session.add(record)
        try:
            await session.flush()
        except IntegrityError:
            # A double tap: the other request created it first.
            await session.rollback()
            raise await _refuse(
                session,
                user_id,
                attempt,
                409,
                ErrorCode.ATTENDANCE_ALREADY_CHECKED_IN,
                "Already checked in to this shift",
                {"shift_code": w.code},
            ) from None
    else:
        assert record is not None
        record.checkout_status = "checked_out"
        record.check_out_at = stamp
        record.check_out_lat = lat
        record.check_out_lng = lng
        record.check_out_accuracy_m = accuracy
        record.check_out_distance_m = distance
        record.overtime_minutes = (
            win.overtime_minutes(stamp, record.scheduled_end, rules.checkout_window_min)
            if record.overtime_counts
            else 0
        )
        record.updated_at = utcnow()
    await session.commit()
    return record


# --- Day view ------------------------------------------------------------------------------------


def _scope_roles(viewer: User) -> frozenset[Role]:
    return frozenset(MANAGEABLE_ROLES[viewer.role] & TRACKED_ROLES)


def _day_shift(w: win.ShiftWindows, now: datetime, kpis: dict[str, int]) -> DayShiftOut:
    return DayShiftOut(
        code=w.code,  # type: ignore[arg-type]
        name_km=w.shift.name_km,
        name_en=w.shift.name_en,
        start=_local(w.start),  # type: ignore[arg-type]
        end=_local(w.end),  # type: ignore[arg-type]
        check_in_until=_local(win.shown_until(w.check_in_closes)),  # type: ignore[arg-type]
        check_out_until=_local(win.shown_until(w.check_out_closes)),  # type: ignore[arg-type]
        phase=phase(w, now),  # type: ignore[arg-type]
        kpis=ShiftKpis(**kpis),
    )


async def day_view(
    session: AsyncSession,
    viewer: User,
    day: date | None,
    workplace_id: uuid.UUID | None = None,
) -> DayOut:
    """KPIs per shift and per workplace, one row per employee in scope. Each row is evaluated
    with its workplace's schedule: the workplace of that day's records when there are some (they
    keep it), else the employee's current one."""
    now = clock.now()
    zone = tz()
    day = day or win.work_date(now, zone)
    roles = _scope_roles(viewer)
    day_end = win.local(day + timedelta(days=1), win.DAY_START, zone)

    all_workplaces = {
        w.id: w
        for w in await session.scalars(
            select(AttendanceWorkplace).order_by(
                AttendanceWorkplace.is_default.desc(), func.lower(AttendanceWorkplace.name)
            )
        )
    }
    if workplace_id is not None and workplace_id not in all_workplaces:
        raise AppError(404, ErrorCode.ATTENDANCE_WORKPLACE_NOT_FOUND, "Workplace not found")
    default = next((w for w in all_workplaces.values() if w.is_default and w.is_active), None)
    days = await load_days(session, list(all_workplaces.values()), day, day)

    def effective(wid: uuid.UUID | None) -> uuid.UUID | None:
        w = all_workplaces.get(wid) if wid else None
        if w is not None and w.is_active:
            return w.id
        return default.id if default else None

    records = list(
        await session.scalars(
            select(AttendanceRecord)
            .join(User, User.id == AttendanceRecord.user_id)
            .where(AttendanceRecord.work_date == day, User.role.in_(roles))
        )
    )
    with_records = {r.user_id for r in records}
    users = list(
        await session.scalars(
            select(User).where(
                User.role.in_(roles),
                or_(
                    and_(User.is_active, User.created_at < day_end),
                    User.id.in_(with_records) if with_records else false(),
                ),
            )
        )
    )
    users.sort(key=lambda u: (u.role != Role.SUPERVISOR, u.full_name.casefold()))
    refs = await user_refs(session, {r.corrected_by for r in records})
    by_user: dict[uuid.UUID, dict[str, AttendanceRecord]] = {}
    for r in records:
        by_user.setdefault(r.user_id, {})[r.shift_code] = r

    def row_workplace(u: User) -> uuid.UUID | None:
        own = by_user.get(u.id)
        if own:
            first = min(own.values(), key=lambda r: r.scheduled_start)
            if first.workplace_id in all_workplaces:
                return first.workplace_id
        return effective(u.workplace_id)

    def resolved(wid: uuid.UUID | None) -> uuid.UUID | None:
        return wid if wid in all_workplaces else (default.id if default else None)

    def windows_for(wid: uuid.UUID | None) -> list[win.ShiftWindows]:
        """The shifts' times (also on a day off: the headline and kept records need them)."""
        w = resolved(wid)
        return days.schedule(w, day).windows(day) if w else []

    def off_at(wid: uuid.UUID | None) -> DayOff | None:
        w = resolved(wid)
        return days.day_off(w, day) if w else None

    def empty() -> dict[str, int]:
        return dict.fromkeys(ShiftKpis.model_fields, 0)

    kpis: dict[str, dict[str, int]] = {}
    per_workplace: dict[uuid.UUID | None, dict[str, dict[str, int]]] = {}
    rows = []
    starts_later: list[DayRow] = []
    not_tracked: list[DayRow] = []
    for u in users:
        wid = row_workplace(u)
        if workplace_id is not None and wid != workplace_id:
            continue
        cells: dict[str, DayCell] = {}
        status = status_on(u, day, u.attendance_periods)
        if status in ("not_started", "untracked"):
            # Not expected and in no KPI; only records already made (kept) are shown.
            w_obj = all_workplaces.get(wid) if wid else None
            group = starts_later if status == "not_started" else not_tracked
            group.append(
                DayRow(
                    user=UserRef.model_validate(u),
                    role=u.role,
                    position=u.position,
                    is_active=u.is_active,
                    workplace=UserWorkplace(id=w_obj.id, name=w_obj.name) if w_obj else None,
                    day_off=None,
                    starts_on=u.attendance_start_date if status == "not_started" else None,
                    shifts={
                        code: DayCell(state="recorded", record=record_out(r, refs))
                        for code, r in by_user.get(u.id, {}).items()
                    },
                )
            )
            continue
        wk = per_workplace.setdefault(wid, {})
        off = off_at(wid)
        for w in windows_for(wid):
            counters = (kpis.setdefault(w.code, empty()), wk.setdefault(w.code, empty()))
            r = by_user.get(u.id, {}).get(w.code)
            if off is not None:
                # Not counted; a kept (corrected) record is still shown.
                cells[w.code] = (
                    DayCell(state="recorded", record=record_out(r, refs))
                    if r is not None
                    else DayCell(state="day_off", record=None)
                )
                continue
            if r is None:
                state = "not_yet" if now < w.check_in_closes else "no_record"
                keys = ["expected", state]
                cells[w.code] = DayCell(state=state, record=None)  # type: ignore[arg-type]
            else:
                keys = ["expected", r.status]
                if r.checkout_status:
                    keys.append(r.checkout_status)
                cells[w.code] = DayCell(state="recorded", record=record_out(r, refs))
            for k in counters:
                for key in keys:
                    k[key] += 1
        w_obj = all_workplaces.get(wid) if wid else None
        rows.append(
            DayRow(
                user=UserRef.model_validate(u),
                role=u.role,
                position=u.position,
                is_active=u.is_active,
                workplace=UserWorkplace(id=w_obj.id, name=w_obj.name) if w_obj else None,
                day_off=day_off_out(off),
                shifts=cells,
            )
        )

    # The headline shifts: the filtered workplace's times, else the default's.
    headline_id = workplace_id if workplace_id is not None else effective(None)
    headline = windows_for(headline_id)
    shown = [
        wid
        for wid in all_workplaces
        if (workplace_id is None and all_workplaces[wid].is_active)
        or wid == workplace_id
        or wid in per_workplace
    ]
    return DayOut(
        date=day,
        timezone=get_settings().business_timezone,
        server_time=now.astimezone(zone),
        workplace_id=workplace_id,
        day_off=day_off_out(off_at(headline_id)),
        shifts=[_day_shift(w, now, kpis.get(w.code, empty())) for w in headline],
        workplaces=[
            DayWorkplaceOut(
                id=wid,
                name=all_workplaces[wid].name,
                is_default=all_workplaces[wid].is_default,
                day_off=day_off_out(off_at(wid)),
                shifts=[
                    _day_shift(w, now, per_workplace.get(wid, {}).get(w.code, empty()))
                    for w in windows_for(wid)
                ],
            )
            for wid in shown
        ],
        workplace_options=[
            UserWorkplace(id=w.id, name=w.name) for w in all_workplaces.values() if w.is_active
        ],
        rows=rows,
        starts_later=starts_later,
        not_tracked=not_tracked,
    )


# --- Corrections ---------------------------------------------------------------------------------


def _state(r: AttendanceRecord) -> dict[str, Any]:
    return {
        "status": r.status,
        "late_minutes": r.late_minutes,
        "early_minutes": r.early_minutes,
        "check_in_at": _iso(r.check_in_at),
        "checkout_status": r.checkout_status,
        "check_out_at": _iso(r.check_out_at),
        "overtime_minutes": r.overtime_minutes,
    }


def _field_error(field: str, msg: str) -> AppError:
    return AppError(
        422,
        ErrorCode.VALIDATION_ERROR,
        msg,
        {"fields": [{"loc": ["body", field], "type": "value_error", "msg": msg}]},
    )


def _apply(r: AttendanceRecord, body: CorrectionIn, limits: tuple[int, int]) -> None:
    """Set the corrected times; late / early / overtime minutes are recomputed from them, the
    record's snapshot times and flags. `limits`: (open_before_min, checkout_window_min) caps."""
    zone = tz()
    open_before, checkout_window = limits
    if body.status == "absent":
        r.status = "absent"
        r.late_minutes = r.early_minutes = r.overtime_minutes = 0
        r.check_in_at = r.check_in_lat = r.check_in_lng = None
        r.check_in_accuracy_m = r.check_in_distance_m = None
        _clear_check_out(r)
        r.checkout_status = None
        return
    if body.check_in_time is None:
        raise _field_error("check_in_time", "A check-in time is required")
    check_in = win.local(r.work_date, body.check_in_time, zone)
    late = win.late_minutes(check_in, r.scheduled_start)
    r.check_in_at = check_in
    r.late_minutes = late
    r.early_minutes = (
        win.early_minutes(check_in, r.scheduled_start, open_before) if r.early_counts else 0
    )
    r.status = "late" if late else "present"
    checkout = body.checkout_status or ("checked_out" if body.check_out_time else None)
    if checkout == "checked_out":
        if body.check_out_time is None:
            raise _field_error("check_out_time", "A check-out time is required")
        check_out = win.local(r.work_date, body.check_out_time, zone)
        if check_out < check_in:
            raise _field_error("check_out_time", "Check-out can't be before check-in")
        if r.check_out_at != check_out:
            r.check_out_at = check_out
        r.checkout_status = "checked_out"
    else:
        _clear_check_out(r)
        r.checkout_status = checkout
    r.overtime_minutes = (
        win.overtime_minutes(r.check_out_at, r.scheduled_end, checkout_window)
        if r.overtime_counts
        else 0
    )


def _clear_check_out(r: AttendanceRecord) -> None:
    r.check_out_at = r.check_out_lat = r.check_out_lng = None
    r.check_out_accuracy_m = r.check_out_distance_m = None


async def _limits(
    session: AsyncSession, workplace_id: uuid.UUID | None, day: date
) -> tuple[int, int]:
    """Caps for recomputed early / overtime minutes: the windows of the record's workplace's
    schedule on its date (the record snapshots its times and flags, not the window lengths)."""
    w = await session.get(AttendanceWorkplace, workplace_id) if workplace_id else None
    if w is None:
        w = await default_workplace(session)
    if w is None:
        return OPEN_BEFORE_MAX, CHECKOUT_WINDOW_MAX
    v = version_on((await versions_of(session, [w.id]))[w.id], day)
    if v is None:
        return OPEN_BEFORE_MAX, CHECKOUT_WINDOW_MAX
    return v.open_before_min, v.checkout_window_min


async def _target(session: AsyncSession, actor: User, user_id: uuid.UUID) -> User:
    target = await get_user_or_404(session, user_id, actor)
    ensure_can_manage(actor, target)
    if target.role not in TRACKED_ROLES:
        raise AppError(
            422, ErrorCode.ATTENDANCE_NOT_REQUIRED, "Attendance isn't recorded for this account"
        )
    return target


def _mark_corrected(
    session: AsyncSession,
    actor: User,
    r: AttendanceRecord,
    reason: str,
    before: dict[str, Any] | None,
) -> None:
    now = utcnow()
    r.corrected = True
    r.correction_reason = reason
    r.corrected_by = actor.id
    r.corrected_at = now
    r.updated_at = now
    audit(
        session,
        "attendance.correct",
        actor_id=actor.id,
        target_user_id=r.user_id,
        entity_type=ENTITY_RECORD,
        entity_id=r.id,
        details={
            "work_date": r.work_date.isoformat(),
            "shift": r.shift_code,
            "reason": reason,
            "created": before is None,
            "before": before,
            "after": _state(r),
        },
    )


async def correct(
    session: AsyncSession, actor: User, record_id: uuid.UUID, body: CorrectionIn
) -> AttendanceRecord:
    r = await session.scalar(
        select(AttendanceRecord).where(AttendanceRecord.id == record_id).with_for_update()
    )
    if r is None:
        raise AppError(404, ErrorCode.ATTENDANCE_RECORD_NOT_FOUND, "Attendance record not found")
    try:
        await _target(session, actor, r.user_id)
    except AppError as e:
        if e.code == ErrorCode.USER_NOT_FOUND:
            raise AppError(
                404, ErrorCode.ATTENDANCE_RECORD_NOT_FOUND, "Attendance record not found"
            ) from None
        raise
    await ensure_unlocked(session, r.user_id, r.work_date)
    before = _state(r)
    _apply(r, body, await _limits(session, r.workplace_id, r.work_date))
    if _state(r) == before and r.correction_reason == body.reason:
        return r  # nothing changed: no audit entry
    _mark_corrected(session, actor, r, body.reason, before)
    await session.commit()
    return r


async def create_record(
    session: AsyncSession, actor: User, body: RecordCreateIn
) -> AttendanceRecord:
    """Add a missing record (e.g. someone checked in on paper). The shift's times on that date
    at the employee's workplace are snapshotted (also on a day off: a corrected record stays)."""
    target = await _target(session, actor, body.user_id)
    zone = tz()
    if body.work_date > win.work_date(clock.now(), zone):
        raise _field_error("work_date", "The date can't be in the future")
    await ensure_unlocked(session, target.id, body.work_date)
    found = await user_days(session, target, body.work_date, body.work_date)
    schedule = found[1].schedule(found[0].id, body.work_date) if found else None
    shift = schedule.shift(body.shift_code) if schedule else None
    if schedule is None or shift is None:
        raise _field_error("shift_code", "Unknown shift")
    w = win.shift_windows(shift, schedule.rules, body.work_date, zone)
    r = AttendanceRecord(
        user_id=target.id,
        work_date=body.work_date,
        shift_code=shift.code,
        workplace_id=schedule.workplace.id,
        scheduled_start=w.start,
        scheduled_end=w.end,
        status="absent",
        late_minutes=0,
        early_counts=schedule.rules.count_early_checkin,
        overtime_counts=schedule.rules.count_overtime,
        source="correction",
    )
    _apply(r, body, (schedule.rules.open_before_min, schedule.rules.checkout_window_min))
    session.add(r)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        raise AppError(
            409, ErrorCode.ATTENDANCE_RECORD_EXISTS, "This shift already has a record"
        ) from None
    _mark_corrected(session, actor, r, body.reason, None)
    await session.commit()
    return r


# --- Workplaces ----------------------------------------------------------------------------------


def _windows_out(w: win.ShiftWindows) -> ShiftWindowsOut:
    def t(value: datetime) -> str:
        return value.astimezone(tz()).strftime("%H:%M")

    return ShiftWindowsOut(
        check_in_opens=t(w.check_in_opens),
        check_in_until=t(win.shown_until(w.check_in_closes)),
        late_after=t(w.start),
        absent_from=t(w.check_in_closes),
        check_out_opens=t(w.check_out_opens),
        check_out_until=t(win.shown_until(w.check_out_closes)),
        forgot_from=t(w.check_out_closes),
    )


def schedule_out(schedule: Schedule, day: date, refs: dict[uuid.UUID, UserRef]) -> ScheduleOut:
    """A version with its shifts' windows (as times of day, computed on `day`)."""
    v = schedule.version
    windows = {x.code: x for x in schedule.windows(day)}
    return ScheduleOut(
        id=v.id,
        effective_from=v.effective_from,
        weekdays=schedule.weekdays,
        shifts=[
            ShiftOut(
                code=d.code,  # type: ignore[arg-type]
                name_km=d.name_km,
                name_en=d.name_en,
                start_time=d.start,
                end_time=d.end,
                position=d.position,
                windows=_windows_out(windows[d.code]),
            )
            for d in schedule.defs
        ],
        **{f: getattr(v, f) for f in RULE_FIELDS},
        created_by=refs.get(v.created_by) if v.created_by else None,
        created_at=v.created_at or utcnow(),
    )


def _assigned(workplace_ids: list[uuid.UUID]):  # noqa: ANN202 (SQL condition)
    """Active tracked employees assigned to these workplaces."""
    return and_(User.workplace_id.in_(workplace_ids), User.is_active, User.role.in_(TRACKED_ROLES))


async def workplaces_out(
    session: AsyncSession, workplaces: list[AttendanceWorkplace], *, employees: bool = False
) -> list[WorkplaceOut]:
    if not workplaces:
        return []
    ids = [w.id for w in workplaces]
    day = win.work_date(clock.now(), tz())
    versions = await versions_of(session, ids)
    current = {
        w.id: version_on(versions[w.id], day) or default_version(w.id, day) for w in workplaces
    }
    counts: dict[uuid.UUID, int] = {
        wid: n
        for wid, n in (
            await session.execute(
                select(User.workplace_id, func.count())
                .where(_assigned(ids))
                .group_by(User.workplace_id)
            )
        ).all()
    }
    history = set(
        await session.scalars(
            select(AttendanceRecord.workplace_id)
            .where(AttendanceRecord.workplace_id.in_(ids))
            .distinct()
        )
    )
    people: dict[uuid.UUID, list[User]] = {}
    if employees:
        for u in await session.scalars(select(User).where(_assigned(ids))):
            people.setdefault(u.workplace_id, []).append(u)  # type: ignore[arg-type]
    refs = await user_refs(
        session,
        {x for w in workplaces for x in (w.created_by, w.updated_by)}
        | {v.created_by for v in current.values()},
    )
    out = []
    for w in workplaces:
        brief = workplace_brief(w)
        assert brief is not None
        staff = sorted(
            people.get(w.id, []),
            key=lambda u: (u.role != Role.SUPERVISOR, u.full_name.casefold()),
        )
        out.append(
            WorkplaceOut(
                **brief.model_dump(),
                is_default=w.is_default,
                is_active=w.is_active,
                archived_at=w.archived_at,
                timezone=get_settings().business_timezone,
                schedule=schedule_out(Schedule(w, current[w.id]), day, refs),
                employee_count=counts.get(w.id, 0),
                has_history=w.id in history,
                employees=[
                    WorkplaceEmployee(
                        user=UserRef.model_validate(u), role=u.role, position=u.position
                    )
                    for u in staff
                ]
                if employees
                else None,
                created_by=refs.get(w.created_by) if w.created_by else None,
                created_at=w.created_at,
                updated_by=refs.get(w.updated_by) if w.updated_by else None,
                updated_at=w.updated_at,
            )
        )
    return out


async def workplace_out(
    session: AsyncSession, w: AttendanceWorkplace, *, employees: bool = True
) -> WorkplaceOut:
    (out,) = await workplaces_out(session, [w], employees=employees)
    return out


async def list_workplaces(
    session: AsyncSession, *, include_archived: bool = False
) -> list[AttendanceWorkplace]:
    stmt = select(AttendanceWorkplace).order_by(
        AttendanceWorkplace.is_active.desc(),
        AttendanceWorkplace.is_default.desc(),
        func.lower(AttendanceWorkplace.name),
    )
    if not include_archived:
        stmt = stmt.where(AttendanceWorkplace.is_active)
    return list(await session.scalars(stmt))


async def get_workplace(
    session: AsyncSession, workplace_id: uuid.UUID, *, lock: bool = False
) -> AttendanceWorkplace:
    stmt = select(AttendanceWorkplace).where(AttendanceWorkplace.id == workplace_id)
    if lock:
        stmt = stmt.with_for_update()
    w = await session.scalar(stmt)
    if w is None:
        raise AppError(404, ErrorCode.ATTENDANCE_WORKPLACE_NOT_FOUND, "Workplace not found")
    return w


def _archived() -> AppError:
    return AppError(409, ErrorCode.WORKPLACE_ARCHIVED, "The workplace is archived")


def _name_taken(name: str) -> AppError:
    return AppError(
        409, ErrorCode.WORKPLACE_NAME_TAKEN, "Another workplace has this name", {"name": name}
    )


def _text(value: Any) -> Any:
    return str(value) if isinstance(value, Decimal) else value


async def _ensure_name_free(
    session: AsyncSession, name: str, exclude: uuid.UUID | None = None
) -> None:
    stmt = select(AttendanceWorkplace.id).where(
        AttendanceWorkplace.is_active,
        func.lower(AttendanceWorkplace.name) == name.lower(),
    )
    if exclude is not None:
        stmt = stmt.where(AttendanceWorkplace.id != exclude)
    if await session.scalar(stmt.limit(1)) is not None:
        raise _name_taken(name)


def _check_coordinates(body: WorkplaceCreate | WorkplaceUpdate) -> None:
    fields = body.model_fields_set
    if ("latitude" in fields) != ("longitude" in fields) or (
        (body.latitude is None) != (body.longitude is None)
    ):
        raise _field_error("latitude", "Latitude and longitude go together")


async def _flush_name(session: AsyncSession, name: str) -> None:
    """Flush; a concurrent workplace with the same name hits the unique index."""
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        raise _name_taken(name) from None


async def create_workplace(
    session: AsyncSession, actor: User, body: WorkplaceCreate
) -> AttendanceWorkplace:
    """A new workplace whose schedule is a copy of the default workplace's current version,
    effective from today."""
    _check_coordinates(body)
    assert body.name is not None
    name = body.name
    await _ensure_name_free(session, name)
    default = await default_workplace(session)
    w = AttendanceWorkplace(
        name=name,
        address=body.address,
        latitude=_q(body.latitude, "0.000001") if body.latitude is not None else None,
        longitude=_q(body.longitude, "0.000001") if body.longitude is not None else None,
        radius_m=body.radius_m,
        is_default=False,
        created_by=actor.id,
        updated_by=actor.id,
    )
    session.add(w)
    await _flush_name(session, name)
    day = win.work_date(clock.now(), tz())
    source = (
        version_on((await versions_of(session, [default.id]))[default.id], day) if default else None
    )
    session.add(
        copy_version(source, w.id, day, actor.id)
        if source is not None
        else AttendanceScheduleVersion(**_default_values(w.id, day), created_by=actor.id)
    )
    audit(
        session,
        "workplace.create",
        actor_id=actor.id,
        entity_type=ENTITY_WORKPLACE,
        entity_id=w.id,
        details={
            "name": w.name,
            "address": w.address,
            "latitude": _text(w.latitude),
            "longitude": _text(w.longitude),
            "radius_m": w.radius_m,
            "schedule_from": default.name if default else None,
        },
    )
    await session.commit()
    await session.refresh(w)
    return w


async def update_workplace(
    session: AsyncSession, actor: User, workplace_id: uuid.UUID, body: WorkplaceUpdate
) -> AttendanceWorkplace:
    w = await get_workplace(session, workplace_id, lock=True)
    if not w.is_active:
        raise _archived()
    _check_coordinates(body)
    fields = body.model_fields_set
    changes: dict[str, list[Any]] = {}

    def _set(attr: str, value: Any) -> None:
        old = getattr(w, attr)
        if old != value:
            changes[attr] = [_text(old), _text(value)]
            setattr(w, attr, value)

    if "name" in fields and body.name is not None and body.name != w.name:
        await _ensure_name_free(session, body.name, exclude=w.id)
        _set("name", body.name)
    if "address" in fields:
        _set("address", body.address)
    if "latitude" in fields:
        _set("latitude", _q(body.latitude, "0.000001") if body.latitude is not None else None)
        _set("longitude", _q(body.longitude, "0.000001") if body.longitude is not None else None)
    if "radius_m" in fields and body.radius_m is not None:
        _set("radius_m", body.radius_m)
    if body.is_default and not w.is_default:
        if not w.has_coordinates:
            raise _field_error("is_default", "Set the workplace's location first")
        previous = await session.scalar(
            select(AttendanceWorkplace)
            .where(AttendanceWorkplace.is_default, AttendanceWorkplace.id != w.id)
            .with_for_update()
        )
        if previous is not None:
            # Unset first: the partial unique index allows one default at a time.
            previous.is_default = False
            previous.updated_by = actor.id
            previous.updated_at = utcnow()
            await session.flush()
            changes["previous_default"] = [previous.name, None]
        _set("is_default", True)
    if changes:
        w.updated_by = actor.id
        w.updated_at = utcnow()
        await _flush_name(session, w.name)
        audit(
            session,
            "workplace.update",
            actor_id=actor.id,
            entity_type=ENTITY_WORKPLACE,
            entity_id=w.id,
            details={"name": w.name, "changes": changes},
        )
        await session.commit()
        await session.refresh(w)
    return w


async def delete_workplace(session: AsyncSession, actor: User, workplace_id: uuid.UUID) -> str:
    """Refused for the default and while active employees are assigned. With attendance history
    the workplace is archived (records keep their `workplace_id`), otherwise deleted. Returns
    "archived" or "deleted"."""
    w = await get_workplace(session, workplace_id, lock=True)
    if not w.is_active:
        return "archived"
    if w.is_default:
        raise AppError(
            409, ErrorCode.WORKPLACE_IS_DEFAULT, "The default workplace can't be deleted"
        )
    employees = await session.scalar(select(func.count(User.id)).where(_assigned([w.id]))) or 0
    if employees:
        raise AppError(
            409,
            ErrorCode.WORKPLACE_IN_USE,
            "Employees are assigned to this workplace",
            {"employees": employees},
        )
    has_history = (
        await session.scalar(
            select(AttendanceRecord.id).where(AttendanceRecord.workplace_id == w.id).limit(1)
        )
        is not None
    )
    name = w.name
    if has_history:
        w.is_active = False
        w.archived_at = utcnow()
        w.updated_by = actor.id
        w.updated_at = w.archived_at
        action, result = "workplace.archive", "archived"
    else:
        # Inactive / non-tracked users pointing here lose the link (FK SET NULL); its shifts
        # go with it (CASCADE).
        await session.execute(delete(AttendanceWorkplace).where(AttendanceWorkplace.id == w.id))
        session.expunge(w)
        action, result = "workplace.delete", "deleted"
    audit(
        session,
        action,
        actor_id=actor.id,
        entity_type=ENTITY_WORKPLACE,
        entity_id=workplace_id,
        details={"name": name},
    )
    await session.commit()
    return result


async def restore_workplace(
    session: AsyncSession, actor: User, workplace_id: uuid.UUID
) -> AttendanceWorkplace:
    w = await get_workplace(session, workplace_id, lock=True)
    if w.is_active:
        return w
    await _ensure_name_free(session, w.name, exclude=w.id)
    w.is_active = True
    w.archived_at = None
    w.updated_by = actor.id
    w.updated_at = utcnow()
    await _flush_name(session, w.name)
    audit(
        session,
        "workplace.restore",
        actor_id=actor.id,
        entity_type=ENTITY_WORKPLACE,
        entity_id=w.id,
        details={"name": w.name},
    )
    await session.commit()
    await session.refresh(w)
    return w


# --- Summary -------------------------------------------------------------------------------------


async def _summary(
    session: AsyncSession, user: User, year: int | None, month: int | None
) -> SummaryOut:
    zone = tz()
    today = win.work_date(clock.now(), zone)
    try:
        p = summ.period(year, month, today)
    except summ.PeriodError as e:
        raise _field_error(e.field, str(e)) from None
    # Dates before the account existed aren't listed.
    since = user.attendance_start_date or user.created_at.astimezone(zone).date()
    periods = user.attendance_periods
    first = max(p.start, since)
    records = list(
        await session.scalars(
            select(AttendanceRecord)
            .where(
                AttendanceRecord.user_id == user.id,
                AttendanceRecord.work_date >= p.start,
                AttendanceRecord.work_date <= p.end,
            )
            .order_by(AttendanceRecord.work_date, AttendanceRecord.scheduled_start)
        )
    )
    current = await user_workplace(session, user)
    record_workplaces = {r.workplace_id for r in records if r.workplace_id is not None}
    known = (
        list(
            await session.scalars(
                select(AttendanceWorkplace).where(AttendanceWorkplace.id.in_(record_workplaces))
            )
        )
        if record_workplaces
        else []
    )
    if current is not None and current.id not in {w.id for w in known}:
        known.append(current)
    calendar = await load_days(session, known, p.start, p.end)
    names = {s["code"]: (s["name_km"], s["name_en"]) for s in DEFAULT_SHIFTS}
    if current is not None:
        names.update(
            {d.code: (d.name_km, d.name_en) for d in calendar.schedule(current.id, today).defs}
        )
    codes = [c for c in SHIFT_CODES if c in names]
    by_day: dict[date, dict[str, AttendanceRecord]] = {}
    for r in records:
        by_day.setdefault(r.work_date, {})[r.shift_code] = r

    def off_on(day: date) -> DayOff | None:
        """At the workplace of that day's records (they keep it), else the current one."""
        recorded = by_day.get(day)
        first_record = min(recorded.values(), key=lambda r: r.scheduled_start) if recorded else None
        wid = (
            first_record.workplace_id
            if first_record is not None and first_record.workplace_id in calendar.workplaces
            else current.id
            if current is not None
            else None
        )
        return calendar.day_off(wid, day) if wid is not None else None

    offs = {d: off_on(d) for d in {r.work_date for r in records}}
    # Days off and days inside an untracked period (kept records show, but don't count).
    k = summ.kpis(
        (r for r in records if offs[r.work_date] is None and not in_period(periods, r.work_date)),
        codes,
    )
    refs = await user_refs(session, {r.corrected_by for r in records})
    days: list[SummaryDay] = []
    day = p.end
    while day >= p.start:
        recorded = by_day.get(day, {})
        if day >= first or recorded:
            days.append(
                SummaryDay(
                    date=day,
                    day_off=day_off_out(offs[day] if day in offs else off_on(day)),
                    not_tracked=in_period(periods, day),
                    shifts=[
                        SummaryDayShift(
                            code=c,  # type: ignore[arg-type]
                            status=recorded[c].status if c in recorded else "none",  # type: ignore[arg-type]
                            record=record_out(recorded[c], refs) if c in recorded else None,
                        )
                        for c in codes
                    ],
                )
            )
        day -= timedelta(days=1)
    workplace = current
    request_brief, eligibility, locked = None, None, False
    if p.month is not None:
        found = await session.scalar(
            select(AttendanceRequest).where(
                AttendanceRequest.user_id == user.id,
                AttendanceRequest.year == p.year,
                AttendanceRequest.month == p.month,
            )
        )
        eligibility = req.eligibility(
            p.year, p.month, k.balance_minutes, await get_deadline_day(session), today
        )
        if found is not None:
            request_brief = request_brief_out(found, await user_refs(session, {found.reviewed_by}))
            locked = found.status in LOCKING
    return SummaryOut(
        timezone=get_settings().business_timezone,
        period=SummaryPeriod(year=p.year, month=p.month, start=p.start, end=p.end),
        employee=SummaryEmployee(
            user=UserRef.model_validate(user),
            role=user.role,
            position=user.position,
            is_active=user.is_active,
            workplace=UserWorkplace(id=workplace.id, name=workplace.name) if workplace else None,
            since=since,
        ),
        shifts=[
            SummaryShift(code=c, name_km=names[c][0], name_en=names[c][1])  # type: ignore[arg-type]
            for c in codes
        ],
        kpis=SummaryKpis(
            present=SummaryShifts(**vars(k.present)),
            absent=SummaryShifts(**vars(k.absent)),
            late=SummaryCount(**vars(k.late)),
            early=SummaryCount(**vars(k.early)),
            overtime=SummaryCount(**vars(k.overtime)),
            missing_minutes=k.missing_minutes,
            extra_minutes=k.extra_minutes,
            balance_minutes=k.balance_minutes,
            forgot_checkout=k.forgot_checkout,
        ),
        days=days,
        request=request_brief,
        request_eligibility=eligibility,
        month_locked=locked,
    )


async def month_summary(session: AsyncSession, user: User, year: int, month: int) -> SummaryOut:
    """A month's summary of any employee, without scope checks (requests use its KPIs)."""
    return await _summary(session, user, year, month)


async def my_summary(
    session: AsyncSession, user: User, year: int | None, month: int | None
) -> SummaryOut:
    """The employee's own summary (tracked employees only)."""
    if not is_tracked(user):
        raise _not_required()
    return await _summary(session, user, year, month)


async def user_summary(
    session: AsyncSession, actor: User, user_id: uuid.UUID, year: int | None, month: int | None
) -> SummaryOut:
    """An employee's summary for a manager: same scope as corrections (hidden accounts 404,
    outside the scope 403, untracked roles 422 ATTENDANCE_NOT_REQUIRED)."""
    return await _summary(session, await _target(session, actor, user_id), year, month)
