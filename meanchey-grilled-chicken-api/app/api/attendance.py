"""Attendance: check-in / check-out from the Mini App, today's state, the day view, corrections,
workplaces, scheduling (versions, weekdays, holidays) and the calendar."""

import uuid
from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request

from app.attendance.telegram import send_confirmation
from app.bot.notify import deliver
from app.core.errors import AppError, ErrorCode
from app.deps import (
    CurrentUser,
    SessionDep,
    require_any_permission,
    require_permission,
    require_role,
)
from app.models import Role, User
from app.permissions.service import effective_permissions
from app.schemas.attendance import (
    CalendarOut,
    CheckResultOut,
    CorrectionIn,
    DayOut,
    HolidayCopyIn,
    HolidayCopyOut,
    HolidayIn,
    HolidayOut,
    HolidayWriteOut,
    LocationIn,
    MeTodayOut,
    RecordCreateIn,
    RecordOut,
    SchedulingOut,
    SchedulingWriteOut,
    ShiftsIn,
    SummaryOut,
    WeekdaysIn,
    WorkplaceCreate,
    WorkplaceDeleteOut,
    WorkplaceOption,
    WorkplaceOut,
    WorkplaceUpdate,
)
from app.schemas.attendance_request import (
    MyRequestsOut,
    RequestApproveIn,
    RequestCreateIn,
    RequestOut,
    RequestPage,
    RequestRejectIn,
    RequestSettingsIn,
    RequestSettingsOut,
)
from app.services import attendance_service as svc
from app.services import request_service as rsv
from app.services import scheduling_service as sch
from app.services.notification_service import take_queued

router = APIRouter(prefix="/attendance", tags=["attendance"])

CanView = Annotated[User, Depends(require_permission("attendance.view"))]
CanCorrect = Annotated[User, Depends(require_permission("attendance.correct"))]
CanManageWorkplace = Annotated[User, Depends(require_permission("attendance.workplace_manage"))]
CanSchedule = Annotated[User, Depends(require_permission("attendance.scheduling"))]
Superadmin = Annotated[User, Depends(require_role(Role.SUPERADMIN))]
CanReview = Annotated[User, Depends(require_permission("attendance.requests_review"))]
CanViewScheduling = Annotated[
    User, Depends(require_any_permission("attendance.view", "attendance.scheduling"))
]

WORKPLACE_PERMISSIONS = ("attendance.workplace_view", "attendance.workplace_manage")


async def _can_see_workplaces(user: CurrentUser, session: SessionDep) -> User:
    """Either workplace permission."""
    if not (await effective_permissions(session, user)) & set(WORKPLACE_PERMISSIONS):
        raise AppError(
            403,
            ErrorCode.MISSING_PERMISSION,
            "Missing permission",
            {"required": list(WORKPLACE_PERMISSIONS)},
        )
    return user


CanSeeWorkplaces = Annotated[User, Depends(_can_see_workplaces)]


async def _can_pick_workplaces(user: CurrentUser, session: SessionDep) -> User:
    """The user form and the users list (users.view) or any workplace permission."""
    wanted = {"users.view", *WORKPLACE_PERMISSIONS}
    if not (await effective_permissions(session, user)) & wanted:
        raise AppError(
            403, ErrorCode.MISSING_PERMISSION, "Missing permission", {"required": sorted(wanted)}
        )
    return user


CanPickWorkplaces = Annotated[User, Depends(_can_pick_workplaces)]


# --- Me ------------------------------------------------------------------------------------------


@router.get("/me/today", response_model=MeTodayOut)
async def me_today(user: CurrentUser, session: SessionDep) -> MeTodayOut:
    """Tracked employees: server time, both shifts with their windows and records, the
    workplace (map) and the one `next_action`. Others → 403 ATTENDANCE_NOT_REQUIRED."""
    return await svc.me_today(session, user)


Year = Annotated[int | None, Query(ge=2000, le=2100)]
Month = Annotated[int | None, Query(ge=1, le=12)]


@router.get("/me/summary", response_model=SummaryOut)
async def me_summary(
    user: CurrentUser, session: SessionDep, year: Year = None, month: Month = None
) -> SummaryOut:
    """Tracked employees: KPIs and one row per day (period start → today, newest first) for a
    month, or the whole year without `month`; default the current month. Future periods →
    VALIDATION_ERROR."""
    return await svc.my_summary(session, user, year, month)


async def _check(
    action: str,
    body: LocationIn,
    user: User,
    session: SessionDep,
    request: Request,
    background: BackgroundTasks,
) -> CheckResultOut:
    record = await svc.check(session, user, action, body)
    background.add_task(send_confirmation, record.id, action, request.app.state.telegram)
    (out,) = await svc.records_out(session, [record])
    return CheckResultOut(action=action, record=out, today=await svc.me_today(session, user))  # type: ignore[arg-type]


@router.post("/check-in", response_model=CheckResultOut)
async def check_in(
    body: LocationIn,
    user: CurrentUser,
    session: SessionDep,
    request: Request,
    background: BackgroundTasks,
) -> CheckResultOut:
    """The phone's GPS position; the server picks the shift from its own clock. Refusals are
    audited (`attendance.attempt_refused`); a confirmation goes to the user's chat."""
    return await _check("check_in", body, user, session, request, background)


@router.post("/check-out", response_model=CheckResultOut)
async def check_out(
    body: LocationIn,
    user: CurrentUser,
    session: SessionDep,
    request: Request,
    background: BackgroundTasks,
) -> CheckResultOut:
    return await _check("check_out", body, user, session, request, background)


# --- Day view and corrections --------------------------------------------------------------------


@router.get("/day", response_model=DayOut)
async def day(
    actor: CanView,
    session: SessionDep,
    date_: Annotated[date | None, Query(alias="date")] = None,
    workplace_id: uuid.UUID | None = None,
) -> DayOut:
    """KPIs per shift (overall and per workplace) and one row per employee in the viewer's
    scope (default: today), optionally for one workplace."""
    return await svc.day_view(session, actor, date_, workplace_id)


@router.get("/users/{user_id}/summary", response_model=SummaryOut)
async def user_summary(
    user_id: uuid.UUID,
    actor: CanView,
    session: SessionDep,
    year: Year = None,
    month: Month = None,
) -> SummaryOut:
    """The same summary for an employee in the viewer's scope (GM / superadmin: staff and
    supervisors; a supervisor: staff). Hidden accounts → 404."""
    return await svc.user_summary(session, actor, user_id, year, month)


@router.patch("/records/{record_id}", response_model=RecordOut)
async def correct_record(
    record_id: uuid.UUID, body: CorrectionIn, actor: CanCorrect, session: SessionDep
) -> RecordOut:
    """Fix a record with a required reason (audited `attendance.correct`)."""
    record = await svc.correct(session, actor, record_id, body)
    (out,) = await svc.records_out(session, [record])
    return out


@router.post("/records", response_model=RecordOut, status_code=201)
async def create_record(body: RecordCreateIn, actor: CanCorrect, session: SessionDep) -> RecordOut:
    """Add a missing record (409 ATTENDANCE_RECORD_EXISTS if the shift has one)."""
    record = await svc.create_record(session, actor, body)
    (out,) = await svc.records_out(session, [record])
    return out


# --- Workplaces and their schedules --------------------------------------------------------------


@router.get("/workplace-options", response_model=list[WorkplaceOption])
async def workplace_options(_: CanPickWorkplaces, session: SessionDep) -> list[WorkplaceOption]:
    """Active workplaces (id, name, default first) for assigning employees and filtering the
    users list: no location or rules."""
    return [
        WorkplaceOption(id=w.id, name=w.name, is_default=w.is_default)
        for w in await svc.list_workplaces(session)
    ]


@router.get("/workplaces", response_model=list[WorkplaceOut])
async def list_workplaces(
    _: CanSeeWorkplaces,
    session: SessionDep,
    include_archived: bool = False,
) -> list[WorkplaceOut]:
    """Each workplace with its location, radius, current schedule (read-only), assigned active
    employee count and `is_default`. Archived ones only with `include_archived`."""
    workplaces = await svc.list_workplaces(session, include_archived=include_archived)
    return await svc.workplaces_out(session, workplaces)


@router.post("/workplaces", response_model=WorkplaceOut, status_code=201)
async def create_workplace(
    body: WorkplaceCreate, actor: CanManageWorkplace, session: SessionDep
) -> WorkplaceOut:
    """Name, address, position, radius; the schedule is a copy of the default workplace's
    current version, from today."""
    workplace = await svc.create_workplace(session, actor, body)
    return await svc.workplace_out(session, workplace)


@router.get("/workplaces/{workplace_id}", response_model=WorkplaceOut)
async def get_workplace(
    workplace_id: uuid.UUID, _: CanSeeWorkplaces, session: SessionDep
) -> WorkplaceOut:
    """One workplace, including the active employees assigned to it."""
    return await svc.workplace_out(session, await svc.get_workplace(session, workplace_id))


@router.patch("/workplaces/{workplace_id}", response_model=WorkplaceOut)
async def update_workplace(
    workplace_id: uuid.UUID, body: WorkplaceUpdate, actor: CanManageWorkplace, session: SessionDep
) -> WorkplaceOut:
    """Name, address, position (latitude + longitude together), radius (10–5000 m) and
    `is_default: true` (the previous default stops being it)."""
    workplace = await svc.update_workplace(session, actor, workplace_id, body)
    return await svc.workplace_out(session, workplace)


@router.delete("/workplaces/{workplace_id}", response_model=WorkplaceDeleteOut)
async def delete_workplace(
    workplace_id: uuid.UUID, actor: CanManageWorkplace, session: SessionDep
) -> WorkplaceDeleteOut:
    """409 WORKPLACE_IS_DEFAULT for the default, 409 WORKPLACE_IN_USE (`details.employees`)
    while active employees are assigned. Archived when it has attendance history, else
    deleted (`result`)."""
    result = await svc.delete_workplace(session, actor, workplace_id)
    return WorkplaceDeleteOut(result=result)  # type: ignore[arg-type]


@router.post("/workplaces/{workplace_id}/restore", response_model=WorkplaceOut)
async def restore_workplace(
    workplace_id: uuid.UUID, actor: CanManageWorkplace, session: SessionDep
) -> WorkplaceOut:
    workplace = await svc.restore_workplace(session, actor, workplace_id)
    return await svc.workplace_out(session, workplace)


# --- Scheduling (versions, weekdays, holidays) and the calendar ---------------------------------

WorkplaceIds = Annotated[list[uuid.UUID] | None, Query()]


@router.get("/scheduling", response_model=SchedulingOut)
async def get_scheduling(
    _: CanViewScheduling, session: SessionDep, workplace_ids: WorkplaceIds = None
) -> SchedulingOut:
    """Per chosen workplace (all by default; repeat `workplace_ids`): the current version and
    the upcoming ones; `differs` when the chosen workplaces' current weekdays / shifts and rules
    differ; `workplace_options`: every active workplace."""
    return await sch.scheduling(session, workplace_ids)


async def _write_out(
    session: SessionDep, workplaces: list, effects: sch.Effects
) -> SchedulingWriteOut:
    return SchedulingWriteOut(
        scheduling=await sch.scheduling(session, [w.id for w in workplaces]),
        records_removed=effects.records_removed,
        absents_recreated=effects.absents_recreated,
        skipped_locked=effects.skipped_locked,
    )


@router.put("/scheduling/weekdays", response_model=SchedulingWriteOut)
async def put_weekdays(
    body: WeekdaysIn, actor: CanSchedule, session: SessionDep
) -> SchedulingWriteOut:
    """Tracked weekdays from `effective_from` (default today; past → VALIDATION_ERROR) for the
    workplaces or "all". Making today untracked removes today's records (corrected ones kept)."""
    workplaces, effects = await sch.set_weekdays(session, actor, body)
    return await _write_out(session, workplaces, effects)


@router.put("/scheduling/shifts", response_model=SchedulingWriteOut)
async def put_shifts(body: ShiftsIn, actor: CanSchedule, session: SessionDep) -> SchedulingWriteOut:
    """Both shifts and every rule, validated as one day, from `effective_from`. Records keep
    their snapshot times."""
    workplaces, effects = await sch.set_shifts(session, actor, body)
    return await _write_out(session, workplaces, effects)


@router.delete("/scheduling/versions/{version_id}", status_code=204)
async def delete_version(version_id: uuid.UUID, actor: CanSchedule, session: SessionDep) -> None:
    """Upcoming versions only (409 ATTENDANCE_SCHEDULE_VERSION_IN_EFFECT otherwise)."""
    await sch.delete_version(session, actor, version_id)


@router.get("/calendar", response_model=CalendarOut)
async def get_calendar(
    _: CanViewScheduling,
    session: SessionDep,
    year: Annotated[int, Query(ge=2000, le=2100)],
    month: Annotated[int, Query(ge=1, le=12)],
    workplace_ids: WorkplaceIds = None,
) -> CalendarOut:
    """Each day of the month: tracked / off / mixed at the chosen workplaces (all by default),
    the reason and the holidays; per workplace when several are chosen."""
    return await sch.calendar(session, year, month, workplace_ids)


@router.get("/holidays", response_model=list[HolidayOut])
async def list_holidays(
    _: CanViewScheduling,
    session: SessionDep,
    year: Annotated[int | None, Query(ge=2000, le=2100)] = None,
    workplace_id: uuid.UUID | None = None,
) -> list[HolidayOut]:
    """Holidays overlapping the year (default this year), by start date; with `workplace_id`
    those covering it."""
    return await sch.list_holidays(session, year, workplace_id)


@router.post("/holidays", response_model=HolidayWriteOut, status_code=201)
async def create_holiday(
    body: HolidayIn, actor: CanSchedule, session: SessionDep
) -> HolidayWriteOut:
    """Days up to today lose their attendance records (corrected ones are kept; audited)."""
    h, effects = await sch.create_holiday(session, actor, body)
    return HolidayWriteOut(
        holiday=await sch.holiday_out(session, h),
        records_removed=effects.records_removed,
        absents_recreated=effects.absents_recreated,
        skipped_locked=effects.skipped_locked,
    )


@router.post("/holidays/copy", response_model=HolidayCopyOut, status_code=201)
async def copy_holidays(
    body: HolidayCopyIn, actor: CanSchedule, session: SessionDep
) -> HolidayCopyOut:
    """Every holiday of `from_year` on the same month / day in `to_year` (Feb 29 → Feb 28);
    duplicates (same name and dates) are skipped."""
    created, skipped, effects = await sch.copy_holidays(session, actor, body)
    return HolidayCopyOut(
        created=await sch.holidays_out(session, created),
        skipped=skipped,
        records_removed=effects.records_removed,
        skipped_locked=effects.skipped_locked,
    )


@router.get("/holidays/{holiday_id}", response_model=HolidayOut)
async def get_holiday(
    holiday_id: uuid.UUID, _: CanViewScheduling, session: SessionDep
) -> HolidayOut:
    return await sch.holiday_out(session, await sch.get_holiday(session, holiday_id))


@router.patch("/holidays/{holiday_id}", response_model=HolidayWriteOut)
async def update_holiday(
    holiday_id: uuid.UUID, body: HolidayIn, actor: CanSchedule, session: SessionDep
) -> HolidayWriteOut:
    """The whole holiday. Days newly covered (up to today) lose their records; days no longer
    covered get their absents back."""
    h, effects = await sch.update_holiday(session, actor, holiday_id, body)
    return HolidayWriteOut(
        holiday=await sch.holiday_out(session, h),
        records_removed=effects.records_removed,
        absents_recreated=effects.absents_recreated,
        skipped_locked=effects.skipped_locked,
    )


@router.delete("/holidays/{holiday_id}", response_model=HolidayWriteOut)
async def delete_holiday(
    holiday_id: uuid.UUID, actor: CanSchedule, session: SessionDep
) -> HolidayWriteOut:
    """Past days of the holiday get their absents back."""
    effects = await sch.delete_holiday(session, actor, holiday_id)
    return HolidayWriteOut(
        holiday=None,
        records_removed=effects.records_removed,
        absents_recreated=effects.absents_recreated,
        skipped_locked=effects.skipped_locked,
    )


# --- Requests (a month's missing time: salary cut / unpaid extra work) ---------------------------

RequestStatusFilter = Annotated[
    Literal["pending", "approved", "rejected", "no_request"] | None, Query(alias="status")
]


@router.get("/requests/me", response_model=MyRequestsOut)
async def my_requests(user: CurrentUser, session: SessionDep, year: Year = None) -> MyRequestsOut:
    """Tracked employees: each month of the year (newest first) with its balance, eligibility
    (`eligible`, `not_needed`, `window_not_open`, `window_closed`), window dates and request."""
    return await rsv.my_months(session, user, year)


@router.post("/requests", response_model=RequestOut, status_code=201)
async def create_request(
    body: RequestCreateIn,
    user: CurrentUser,
    session: SessionDep,
    request: Request,
    background: BackgroundTasks,
) -> RequestOut:
    """One request for an ended month whose missing time is at least 1 hour, inside the window
    (1st of the next month to the deadline day). The split must equal the missing time."""
    row = await rsv.submit(session, user, body)
    background.add_task(deliver, take_queued(session), request.app.state.telegram)
    return (await rsv.requests_out(session, [row]))[0]


@router.get("/requests", response_model=RequestPage)
async def list_requests(
    actor: CanReview,
    session: SessionDep,
    status: RequestStatusFilter = None,
    year: Year = None,
    month: Month = None,
    user_id: uuid.UUID | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
) -> RequestPage:
    """Requests of the employees in your scope: pending first (oldest first), then the rest,
    20 per page. `status=no_request`: eligible months whose window is over without a request."""
    return await rsv.list_requests(
        session, actor, status=status, year=year, month=month, user_id=user_id, page=page
    )


@router.get("/requests/{request_id}", response_model=RequestOut)
async def get_request(request_id: uuid.UUID, user: CurrentUser, session: SessionDep) -> RequestOut:
    """The owner, or a reviewer with the employee in scope."""
    return await rsv.detail(session, user, request_id)


@router.post("/requests/{request_id}/approve", response_model=RequestOut)
async def approve_request(
    request_id: uuid.UUID,
    body: RequestApproveIn,
    actor: CanReview,
    session: SessionDep,
    request: Request,
    background: BackgroundTasks,
) -> RequestOut:
    """Pending only. Without splits: as submitted; with a split (sum = the missing time): approve
    with changes (both splits are kept). `comment` is optional."""
    row = await rsv.approve(session, actor, request_id, body)
    background.add_task(deliver, take_queued(session), request.app.state.telegram)
    return (await rsv.requests_out(session, [row]))[0]


@router.post("/requests/{request_id}/reject", response_model=RequestOut)
async def reject_request(
    request_id: uuid.UUID,
    body: RequestRejectIn,
    actor: CanReview,
    session: SessionDep,
    request: Request,
    background: BackgroundTasks,
) -> RequestOut:
    """Pending only; the reason is required. The month is unlocked; no new request for it."""
    row = await rsv.reject(session, actor, request_id, body)
    background.add_task(deliver, take_queued(session), request.app.state.telegram)
    return (await rsv.requests_out(session, [row]))[0]


@router.get("/settings/requests", response_model=RequestSettingsOut)
async def get_request_settings(_: CanReview, session: SessionDep) -> RequestSettingsOut:
    return await rsv.get_settings_out(session)


@router.put("/settings/requests", response_model=RequestSettingsOut)
async def put_request_settings(
    body: RequestSettingsIn, actor: Superadmin, session: SessionDep
) -> RequestSettingsOut:
    """Superadmin only: the last day of the next month on which requests are accepted (1–28)."""
    return await rsv.update_settings(session, actor, body.request_deadline_day)
