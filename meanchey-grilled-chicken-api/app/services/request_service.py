"""Attendance requests: an employee's monthly missing-time request and its review.

- **Eligibility:** `app.attendance.requests` (missing = the month's negative balance, at least an
  hour; window = the 1st of the next month to the deadline day).
- **One request per employee and month**, never edited or withdrawn; after a rejection no new one.
- **Snapshot:** the month's missing / extra / absent / late minutes and balance at submission.
- **Month lock:** pending and approved requests lock the month (`app.attendance.month_lock`).
- **Review:** approve as submitted, approve with another split (both are stored) or reject with a
  reason; scope = the role hierarchy, never your own request.
- **Notifications** (bell + Telegram, after the commit): reviewers in scope on submission, the
  employee on the decision, and the 1st-of-month reminder (`queue_reminders`).
"""

import uuid
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.attendance import clock
from app.attendance import requests as req
from app.attendance import windows as win
from app.attendance.month_lock import LOCKING
from app.attendance.request_settings import (
    get_deadline_day,
    get_marker,
    set_deadline_day,
    set_marker,
)
from app.attendance.workplaces import TRACKED_ROLES, is_tracked
from app.config import get_settings
from app.core.errors import AppError, ErrorCode
from app.models import AttendanceRequest, Notification, Role, User, utcnow
from app.permissions.hierarchy import MANAGEABLE_ROLES, can_manage, ensure_can_manage
from app.permissions.service import effective_permissions
from app.schemas.attendance_request import (
    MyRequestMonth,
    MyRequestsOut,
    RequestApproveIn,
    RequestCreateIn,
    RequestOut,
    RequestPage,
    RequestRejectIn,
    RequestRow,
    RequestSettingsOut,
)
from app.schemas.common import UserRef
from app.services import attendance_service as att
from app.services.audit_service import record as audit
from app.services.notification_service import (
    REQUEST_APPROVED,
    REQUEST_REJECTED,
    REQUEST_REMINDER,
    REQUEST_SUBMITTED,
    notify_users,
    recipients,
)

ENTITY = "attendance_request"
PERMISSION = "attendance.requests_review"
PAGE_SIZE = 20
NO_REQUEST_MONTHS = 3  # months looked at for `no_request` rows when none is chosen


def _today() -> date:
    return win.work_date(clock.now(), get_settings().business_tz)


def _error(status: int, code: ErrorCode, message: str, details: dict | None = None) -> AppError:
    return AppError(status, code, message, details)


def _not_found() -> AppError:
    return _error(404, ErrorCode.ATTENDANCE_REQUEST_NOT_FOUND, "Request not found")


# --- Month figures -------------------------------------------------------------------------------


@dataclass(frozen=True)
class Figures:
    balance: int
    missing: int
    extra: int
    absent: int
    late: int


async def month_figures(session: AsyncSession, user: User, year: int, month: int) -> Figures:
    """The month's KPIs from the summary definitions (the same numbers the employee sees)."""
    k = (await att.month_summary(session, user, year, month)).kpis
    return Figures(
        balance=k.balance_minutes,
        missing=req.missing_minutes(k.balance_minutes),
        extra=k.extra_minutes,
        absent=k.absent.minutes,
        late=k.late.minutes,
    )


# --- Output --------------------------------------------------------------------------------------


async def requests_out(session: AsyncSession, rows: list[AttendanceRequest]) -> list[RequestOut]:
    ids = {r.user_id for r in rows} | {r.reviewed_by for r in rows}
    refs = await att.user_refs(session, ids)
    users = {
        u.id: u
        for u in await session.scalars(select(User).where(User.id.in_({r.user_id for r in rows})))
    }
    out = []
    for r in rows:
        brief = att.request_brief_out(r, refs)
        out.append(
            RequestOut(
                **{name: getattr(brief, name) for name in type(brief).model_fields},
                user=refs[r.user_id],
                position=users[r.user_id].position if r.user_id in users else None,
                year=r.year,
                month=r.month,
                missing_minutes=r.missing_minutes,
                extra_minutes=r.extra_minutes,
                absent_minutes=r.absent_minutes,
                late_minutes=r.late_minutes,
                balance_minutes=r.balance_minutes,
                note=r.note,
                month_locked=r.status in LOCKING,
            )
        )
    return out


# --- Settings ------------------------------------------------------------------------------------


async def get_settings_out(session: AsyncSession) -> RequestSettingsOut:
    return RequestSettingsOut(request_deadline_day=await get_deadline_day(session))


async def update_settings(session: AsyncSession, actor: User, day: int) -> RequestSettingsOut:
    before = await get_deadline_day(session)
    await set_deadline_day(session, day)
    if before != day:
        audit(
            session,
            "attendance.settings_update",
            actor_id=actor.id,
            details={"request_deadline_day": [before, day]},
        )
    await session.commit()
    return RequestSettingsOut(request_deadline_day=day)


# --- The employee's months -----------------------------------------------------------------------


def _need_tracked(user: User) -> None:
    if not is_tracked(user):
        raise _error(
            403, ErrorCode.ATTENDANCE_NOT_REQUIRED, "Attendance isn't recorded for this account"
        )


async def my_months(session: AsyncSession, user: User, year: int | None) -> MyRequestsOut:
    """Per month of the year (newest first, up to the current month, from the month attendance
    started): the figures, the eligibility, the window and the request."""
    _need_tracked(user)
    today = _today()
    year = year or today.year
    if year > today.year:
        raise AppError(422, ErrorCode.VALIDATION_ERROR, "The year can't be in the future")
    deadline = await get_deadline_day(session)
    zone = get_settings().business_tz
    since = user.attendance_start_date or user.created_at.astimezone(zone).date()
    existing = {
        r.month: r
        for r in await session.scalars(
            select(AttendanceRequest).where(
                AttendanceRequest.user_id == user.id, AttendanceRequest.year == year
            )
        )
    }
    refs = await att.user_refs(session, {r.reviewed_by for r in existing.values()})
    last = today.month if year == today.year else 12
    months: list[MyRequestMonth] = []
    for month in range(last, 0, -1):
        if req.month_end(year, month) < since and month not in existing:
            continue
        f = await month_figures(session, user, year, month)
        w = req.window(year, month, deadline)
        found = existing.get(month)
        months.append(
            MyRequestMonth(
                year=year,
                month=month,
                balance_minutes=f.balance,
                missing_minutes=f.missing,
                extra_minutes=f.extra,
                absent_minutes=f.absent,
                late_minutes=f.late,
                eligibility=req.eligibility(year, month, f.balance, deadline, today),
                opens=w.opens,
                closes=w.closes,
                request=att.request_brief_out(found, refs) if found else None,
            )
        )
    return MyRequestsOut(
        timezone=get_settings().business_timezone,
        year=year,
        request_deadline_day=deadline,
        months=months,
    )


# --- Submit --------------------------------------------------------------------------------------


async def _reviewers(session: AsyncSession, employee: User) -> list[User]:
    """Holders of the review permission whose scope includes the employee (and the superadmin)."""
    return [u for u in await recipients(session, PERMISSION) if can_manage(u, employee)]


def _details(r: AttendanceRequest) -> dict[str, Any]:
    return {
        "year": r.year,
        "month": r.month,
        "missing_minutes": r.missing_minutes,
        "extra_minutes": r.extra_minutes,
        "absent_minutes": r.absent_minutes,
        "late_minutes": r.late_minutes,
        "balance_minutes": r.balance_minutes,
        "salary_cut_minutes": r.requested_salary_cut_minutes,
        "unpaid_work_minutes": r.requested_unpaid_work_minutes,
        "type": r.type,
    }


def _payload(r: AttendanceRequest) -> dict[str, Any]:
    """Figures for a notification: the requested split, or the approved one once approved."""
    cut = r.approved_salary_cut_minutes
    work = r.approved_unpaid_work_minutes
    return {
        "year": r.year,
        "month": r.month,
        "missing_minutes": r.missing_minutes,
        "salary_cut_minutes": r.requested_salary_cut_minutes if cut is None else cut,
        "unpaid_work_minutes": r.requested_unpaid_work_minutes if work is None else work,
    }


async def submit(session: AsyncSession, user: User, body: RequestCreateIn) -> AttendanceRequest:
    _need_tracked(user)
    today = _today()
    deadline = await get_deadline_day(session)
    # One per month, also after a rejection.
    if await session.scalar(
        select(AttendanceRequest.id).where(
            AttendanceRequest.user_id == user.id,
            AttendanceRequest.year == body.year,
            AttendanceRequest.month == body.month,
        )
    ):
        raise _error(
            409,
            ErrorCode.ATTENDANCE_REQUEST_EXISTS,
            "A request for this month was already sent",
            {"year": body.year, "month": body.month},
        )
    w = req.window(body.year, body.month, deadline)
    if not w.opens <= today <= w.closes:
        raise _error(
            409,
            ErrorCode.ATTENDANCE_REQUEST_WINDOW_CLOSED,
            "Requests for this month are not open",
            {"opens": w.opens.isoformat(), "closes": w.closes.isoformat()},
        )
    f = await month_figures(session, user, body.year, body.month)
    if f.missing < req.MIN_MISSING_MINUTES:
        raise _error(
            409,
            ErrorCode.ATTENDANCE_REQUEST_NOT_NEEDED,
            "The missing time is under 1 hour: no request is needed",
            {"missing_minutes": f.missing},
        )
    given = body.salary_cut_minutes + body.unpaid_work_minutes
    if given != f.missing:
        raise _error(
            422,
            ErrorCode.ATTENDANCE_REQUEST_SPLIT_MISMATCH,
            "Salary cut and unpaid work must add up to the missing time",
            {"expected": f.missing, "given": given},
        )
    row = AttendanceRequest(
        user_id=user.id,
        year=body.year,
        month=body.month,
        status="pending",
        missing_minutes=f.missing,
        extra_minutes=f.extra,
        absent_minutes=f.absent,
        late_minutes=f.late,
        balance_minutes=f.balance,
        requested_salary_cut_minutes=body.salary_cut_minutes,
        requested_unpaid_work_minutes=body.unpaid_work_minutes,
        type=req.request_type(body.salary_cut_minutes, body.unpaid_work_minutes),
        note=(body.note or "").strip() or None,
        submitted_at=utcnow(),
    )
    session.add(row)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        raise _error(
            409, ErrorCode.ATTENDANCE_REQUEST_EXISTS, "A request for this month was already sent"
        ) from None
    audit(
        session,
        "attendance.request_submit",
        actor_id=user.id,
        target_user_id=user.id,
        entity_type=ENTITY,
        entity_id=row.id,
        details=_details(row),
    )
    notify_users(
        session,
        REQUEST_SUBMITTED,
        await _reviewers(session, user),
        entity_type=ENTITY,
        entity_id=row.id,
        payload={**_payload(row), "name": user.full_name, "actor_id": str(user.id)},
    )
    await session.commit()
    return row


# --- Reading -------------------------------------------------------------------------------------


def _scope_roles(viewer: User) -> frozenset[Role]:
    return frozenset(MANAGEABLE_ROLES[viewer.role] & TRACKED_ROLES)


async def get_request(
    session: AsyncSession, request_id: uuid.UUID, *, lock: bool = False
) -> AttendanceRequest:
    stmt = select(AttendanceRequest).where(AttendanceRequest.id == request_id)
    row = await session.scalar(stmt.with_for_update() if lock else stmt)
    if row is None:
        raise _not_found()
    return row


async def detail(session: AsyncSession, viewer: User, request_id: uuid.UUID) -> RequestOut:
    """The owner, or a holder of the review permission with the employee in scope."""
    row = await get_request(session, request_id)
    if row.user_id != viewer.id:
        if PERMISSION not in await effective_permissions(session, viewer):
            raise AppError(
                403, ErrorCode.MISSING_PERMISSION, "Missing permission", {"required": [PERMISSION]}
            )
        employee = await session.get(User, row.user_id)
        if employee is None:
            raise _not_found()
        ensure_can_manage(viewer, employee)
    return (await requests_out(session, [row]))[0]


def _row(r: AttendanceRequest, ref: UserRef, position: str | None) -> RequestRow:
    return RequestRow(
        id=r.id,
        status=r.status,  # type: ignore[arg-type]
        user=ref,
        position=position,
        year=r.year,
        month=r.month,
        type=r.type,  # type: ignore[arg-type]
        missing_minutes=r.missing_minutes,
        requested_salary_cut_minutes=r.requested_salary_cut_minutes,
        requested_unpaid_work_minutes=r.requested_unpaid_work_minutes,
        approved_salary_cut_minutes=r.approved_salary_cut_minutes,
        approved_unpaid_work_minutes=r.approved_unpaid_work_minutes,
        approved_with_changes=r.approved_with_changes,
        note=r.note,
        submitted_at=r.submitted_at,
    )


def _closed_months(today: date, deadline: int) -> list[tuple[int, int]]:
    """(year, month) whose window is over, newest first."""
    out = []
    y, m = today.year, today.month
    for _ in range(36):
        m -= 1
        if m == 0:
            y, m = y - 1, 12
        if today > req.window(y, m, deadline).closes:
            out.append((y, m))
    return out


async def _no_request_rows(
    session: AsyncSession,
    viewer: User,
    year: int | None,
    month: int | None,
    user_id: uuid.UUID | None,
) -> list[RequestRow]:
    today = _today()
    months = _closed_months(today, await get_deadline_day(session))
    if year is not None:
        months = [(y, m) for y, m in months if y == year]
    if month is not None:
        months = [(y, m) for y, m in months if m == month]
    if year is None and month is None:
        months = months[:NO_REQUEST_MONTHS]
    roles = _scope_roles(viewer)
    if not roles:
        return []
    stmt = (
        select(User).where(User.is_active, User.role.in_(roles)).order_by(User.full_name, User.id)
    )
    if user_id is not None:
        stmt = stmt.where(User.id == user_id)
    employees = list(await session.scalars(stmt))
    have = {
        (r.user_id, r.year, r.month)
        for r in await session.scalars(
            select(AttendanceRequest).where(
                AttendanceRequest.user_id.in_([u.id for u in employees] or [uuid.uuid4()])
            )
        )
    }
    rows: list[RequestRow] = []
    for y, m in months:
        for u in employees:
            if (u.id, y, m) in have:
                continue
            if (
                u.attendance_start_date is not None
                and req.month_end(y, m) < u.attendance_start_date
            ):
                continue
            f = await month_figures(session, u, y, m)
            if f.missing < req.MIN_MISSING_MINUTES:
                continue
            rows.append(
                RequestRow(
                    id=None,
                    status="no_request",
                    user=UserRef.model_validate(u),
                    position=u.position,
                    year=y,
                    month=m,
                    type=None,
                    missing_minutes=f.missing,
                    requested_salary_cut_minutes=None,
                    requested_unpaid_work_minutes=None,
                    approved_salary_cut_minutes=None,
                    approved_unpaid_work_minutes=None,
                    approved_with_changes=False,
                    note=None,
                    submitted_at=None,
                )
            )
    return rows


async def pending_count(session: AsyncSession, viewer: User) -> int:
    roles = _scope_roles(viewer)
    if not roles:
        return 0
    return (
        await session.scalar(
            select(func.count(AttendanceRequest.id))
            .join(User, User.id == AttendanceRequest.user_id)
            .where(AttendanceRequest.status == "pending", User.role.in_(roles))
        )
        or 0
    )


async def list_requests(
    session: AsyncSession,
    viewer: User,
    *,
    status: str | None,
    year: int | None,
    month: int | None,
    user_id: uuid.UUID | None,
    page: int,
) -> RequestPage:
    """Pending first (oldest first), then the others newest first. `no_request`: eligible months
    whose window is over with nobody's request."""
    roles = _scope_roles(viewer)
    pending = await pending_count(session, viewer)
    if status == "no_request":
        rows = await _no_request_rows(session, viewer, year, month, user_id)
        start = (page - 1) * PAGE_SIZE
        return RequestPage(
            items=rows[start : start + PAGE_SIZE],
            total=len(rows),
            page=page,
            page_size=PAGE_SIZE,
            pending_count=pending,
        )
    conditions = [User.role.in_(roles)] if roles else [User.id.is_(None)]
    if status:
        conditions.append(AttendanceRequest.status == status)
    if year:
        conditions.append(AttendanceRequest.year == year)
    if month:
        conditions.append(AttendanceRequest.month == month)
    if user_id:
        conditions.append(AttendanceRequest.user_id == user_id)
    total = (
        await session.scalar(
            select(func.count(AttendanceRequest.id))
            .join(User, User.id == AttendanceRequest.user_id)
            .where(*conditions)
        )
        or 0
    )
    epoch = func.extract("epoch", AttendanceRequest.submitted_at)
    found = (
        await session.execute(
            select(AttendanceRequest, User)
            .join(User, User.id == AttendanceRequest.user_id)
            .where(*conditions)
            .order_by(
                case((AttendanceRequest.status == "pending", 0), else_=1),
                case((AttendanceRequest.status == "pending", epoch), else_=-epoch),
                AttendanceRequest.id,
            )
            .offset((page - 1) * PAGE_SIZE)
            .limit(PAGE_SIZE)
        )
    ).all()
    return RequestPage(
        items=[_row(r, UserRef.model_validate(u), u.position) for r, u in found],
        total=total,
        page=page,
        page_size=PAGE_SIZE,
        pending_count=pending,
    )


# --- Review --------------------------------------------------------------------------------------


async def _reviewable(
    session: AsyncSession, actor: User, request_id: uuid.UUID
) -> tuple[AttendanceRequest, User]:
    row = await get_request(session, request_id, lock=True)
    employee = await session.get(User, row.user_id)
    if employee is None:
        raise _not_found()
    if employee.id == actor.id:
        raise AppError(403, ErrorCode.FORBIDDEN_SCOPE, "You can't review your own request")
    ensure_can_manage(actor, employee)
    if row.status != "pending":
        raise _error(
            409,
            ErrorCode.ATTENDANCE_REQUEST_NOT_PENDING,
            "This request was already reviewed",
            {"status": row.status},
        )
    return row, employee


async def approve(
    session: AsyncSession, actor: User, request_id: uuid.UUID, body: RequestApproveIn
) -> AttendanceRequest:
    """Both splits absent: as submitted. One given: the other is the rest of the missing time.
    `approved_with_changes` is true when the approved split differs from the requested one."""
    row, employee = await _reviewable(session, actor, request_id)
    cut, work = body.salary_cut_minutes, body.unpaid_work_minutes
    if cut is None and work is None:
        cut, work = row.requested_salary_cut_minutes, row.requested_unpaid_work_minutes
    elif cut is None:
        cut = row.missing_minutes - (work or 0)
    elif work is None:
        work = row.missing_minutes - cut
    assert cut is not None and work is not None
    if cut < 0 or work < 0 or cut + work != row.missing_minutes:
        raise _error(
            422,
            ErrorCode.ATTENDANCE_REQUEST_SPLIT_MISMATCH,
            "Salary cut and unpaid work must add up to the missing time",
            {"expected": row.missing_minutes, "given": cut + work},
        )
    before = {
        "salary_cut_minutes": row.requested_salary_cut_minutes,
        "unpaid_work_minutes": row.requested_unpaid_work_minutes,
    }
    changed = (cut, work) != (row.requested_salary_cut_minutes, row.requested_unpaid_work_minutes)
    comment = (body.comment or "").strip() or None
    row.status = "approved"
    row.approved_salary_cut_minutes = cut
    row.approved_unpaid_work_minutes = work
    row.approved_with_changes = changed
    row.review_comment = comment
    row.reviewed_by = actor.id
    row.reviewed_at = utcnow()
    audit(
        session,
        "attendance.request_approve",
        actor_id=actor.id,
        target_user_id=row.user_id,
        entity_type=ENTITY,
        entity_id=row.id,
        details={
            "year": row.year,
            "month": row.month,
            "with_changes": changed,
            "before": before,
            "after": {"salary_cut_minutes": cut, "unpaid_work_minutes": work},
            "comment": comment,
        },
    )
    notify_users(
        session,
        REQUEST_APPROVED,
        [employee],
        entity_type=ENTITY,
        entity_id=row.id,
        payload={
            **_payload(row),
            "with_changes": changed,
            "comment": comment,
            "actor_id": str(actor.id),
        },
    )
    await session.commit()
    return row


async def reject(
    session: AsyncSession, actor: User, request_id: uuid.UUID, body: RequestRejectIn
) -> AttendanceRequest:
    row, employee = await _reviewable(session, actor, request_id)
    reason = body.reason.strip()
    if not reason:
        raise AppError(422, ErrorCode.VALIDATION_ERROR, "A reason is required")
    row.status = "rejected"
    row.reject_reason = reason
    row.reviewed_by = actor.id
    row.reviewed_at = utcnow()
    audit(
        session,
        "attendance.request_reject",
        actor_id=actor.id,
        target_user_id=row.user_id,
        entity_type=ENTITY,
        entity_id=row.id,
        details={"year": row.year, "month": row.month, "reason": reason},
    )
    notify_users(
        session,
        REQUEST_REJECTED,
        [employee],
        entity_type=ENTITY,
        entity_id=row.id,
        payload={**_payload(row), "reason": reason, "actor_id": str(actor.id)},
    )
    await session.commit()
    return row


# --- Reminder (1st of the month) -----------------------------------------------------------------


async def queue_reminders(session: AsyncSession, now: datetime) -> list[uuid.UUID]:
    """On the 1st (business time zone): every tracked employee whose previous month has an
    eligible balance and no request gets one reminder (bell + Telegram when linked). Idempotent:
    an employee already reminded for that month isn't reminded again. Returns the notification
    ids; the caller commits and then hands them to Telegram."""
    day = win.work_date(now, get_settings().business_tz)
    if day.day != 1:
        return []
    year, month = (day.year - 1, 12) if day.month == 1 else (day.year, day.month - 1)
    marker = f"{year}-{month:02d}"
    if await get_marker(session) == marker:
        return []  # the scheduler runs every minute: this month was already handled
    w = req.window(year, month, await get_deadline_day(session))
    reminded = set(
        await session.scalars(
            select(Notification.user_id).where(
                Notification.type == REQUEST_REMINDER,
                Notification.payload["year"].astext == str(year),
                Notification.payload["month"].astext == str(month),
            )
        )
    )
    requested = set(
        await session.scalars(
            select(AttendanceRequest.user_id).where(
                AttendanceRequest.year == year, AttendanceRequest.month == month
            )
        )
    )
    employees = await session.scalars(
        select(User).where(User.is_active, User.role.in_(TRACKED_ROLES)).order_by(User.id)
    )
    ids: list[uuid.UUID] = []
    for u in list(employees):
        if u.id in reminded or u.id in requested:
            continue
        if (
            u.attendance_start_date is not None
            and req.month_end(year, month) < u.attendance_start_date
        ):
            continue
        f = await month_figures(session, u, year, month)
        if f.missing < req.MIN_MISSING_MINUTES:
            continue
        ids += notify_users(
            session,
            REQUEST_REMINDER,
            [u],
            entity_type="user",
            entity_id=u.id,
            payload={
                "year": year,
                "month": month,
                "missing_minutes": f.missing,
                "balance_minutes": f.balance,
                "deadline": w.closes.isoformat(),
                "deadline_day": w.closes.day,
                "deadline_month": w.closes.month,
            },
        )
    await set_marker(session, marker)
    return ids
