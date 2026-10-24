"""Attendance: check-in / check-out, today's state, the day view, corrections, workplaces,
scheduling (schedule versions, tracked weekdays, holidays) and the calendar.

Times of day are "HH:MM" strings (local time in BUSINESS_TIMEZONE); instants are ISO datetimes
with the business offset (e.g. `2026-10-13T07:12:00+07:00`); `timezone` names the zone.
"""

import re
import uuid
from datetime import date, datetime, time
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, BeforeValidator, ConfigDict, Field, PlainSerializer

from app.models.attendance import (
    ABSENT_AFTER_MAX,
    CHECKOUT_WINDOW_MAX,
    HOLIDAY_NAME_MAX_LENGTH,
    HOLIDAY_NOTE_MAX_LENGTH,
    OPEN_BEFORE_MAX,
    RADIUS_MAX_M,
    RADIUS_MIN_M,
    REASON_MAX_LENGTH,
    WORKPLACE_ADDRESS_MAX_LENGTH,
    WORKPLACE_NAME_MAX_LENGTH,
)
from app.models.enums import Role
from app.schemas.attendance_request import Eligibility, RequestBrief
from app.schemas.common import UserRef

_HM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
_SPACES = re.compile(r"\s+")


def _parse_hm(value: object) -> time:
    if isinstance(value, time):
        return value.replace(second=0, microsecond=0)
    if not isinstance(value, str) or not _HM.match(value):
        raise ValueError("Use HH:MM (00:00–23:59)")
    hours, minutes = value.split(":")
    return time(int(hours), int(minutes))


def hm(value: time) -> str:
    return value.strftime("%H:%M")


TimeHM = Annotated[
    time,
    PlainSerializer(hm, return_type=str),
    Field(json_schema_extra={"type": "string", "pattern": _HM.pattern}),
]


# Accepts "HH:MM" only (pydantic's time parser would also take seconds and offsets).
TimeIn = Annotated[time, BeforeValidator(_parse_hm), PlainSerializer(hm, return_type=str)]

ShiftCode = Literal["morning", "afternoon"]
RecordStatus = Literal["present", "late", "absent"]
CheckoutStatus = Literal["checked_out", "forgot_checkout"]
Action = Literal["check_in", "check_out"]


def _name(value: str | None) -> str:
    if value is None:
        raise ValueError("Name is required")
    value = _SPACES.sub(" ", value).strip()
    if not value:
        raise ValueError("Name is required")
    return value


def _optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    value = _SPACES.sub(" ", value).strip()
    return value or None


def _required_int(value: int | None) -> int:
    if value is None:
        raise ValueError("A value is required")
    return value


def _reason(value: str) -> str:
    value = _SPACES.sub(" ", value).strip()
    if not value:
        raise ValueError("A reason is required")
    return value


# --- Workplace -----------------------------------------------------------------------------------


class WorkplaceBrief(BaseModel):
    """The workplace as the check screen needs it (map pin and radius)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    address: str | None
    latitude: float | None
    longitude: float | None
    radius_m: int
    has_coordinates: bool


class UserWorkplace(BaseModel):
    """`UserOut.workplace` and the day view's rows."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str


class WorkplaceOption(UserWorkplace):
    """An active workplace for the user form's select and the users list filter."""

    is_default: bool


class ShiftWindowsOut(BaseModel):
    """A shift's windows as times of day (closing minute included: "until")."""

    check_in_opens: str
    check_in_until: str
    late_after: str
    absent_from: str
    check_out_opens: str
    check_out_until: str
    forgot_from: str


class ShiftOut(BaseModel):
    code: ShiftCode
    name_km: str
    name_en: str
    start_time: TimeHM
    end_time: TimeHM
    position: int
    windows: ShiftWindowsOut


class RulesOut(BaseModel):
    open_before_min: int
    absent_after_min: int
    checkout_window_min: int
    reminders_enabled: bool
    count_early_checkin: bool
    count_overtime: bool


class WorkplaceEmployee(BaseModel):
    user: UserRef
    role: Role
    position: str | None


class ScheduleOut(RulesOut):
    """A schedule version: from `effective_from` on, the tracked weekdays (Monday = 1), both
    shifts with their windows and the rules."""

    id: uuid.UUID
    effective_from: date
    weekdays: list[int]
    shifts: list[ShiftOut]
    created_by: UserRef | None
    created_at: datetime


class WorkplaceOut(WorkplaceBrief):
    """A workplace with its location, its current schedule (read-only: edited in Scheduling)
    and how many active employees are assigned. `employees` is filled by
    `GET /attendance/workplaces/{id}` only."""

    is_default: bool
    is_active: bool
    archived_at: datetime | None
    timezone: str
    schedule: ScheduleOut
    employee_count: int
    has_history: bool
    employees: list[WorkplaceEmployee] | None = None
    created_by: UserRef | None
    created_at: datetime
    updated_by: UserRef | None
    updated_at: datetime


_Name = Annotated[str | None, Field(max_length=WORKPLACE_NAME_MAX_LENGTH), AfterValidator(_name)]
_Address = Annotated[
    str | None, Field(max_length=WORKPLACE_ADDRESS_MAX_LENGTH), AfterValidator(_optional_text)
]
_Latitude = Annotated[float | None, Field(ge=-90, le=90)]
_Longitude = Annotated[float | None, Field(ge=-180, le=180)]


class WorkplaceCreate(BaseModel):
    """A new workplace; its schedule is copied from the default workplace."""

    model_config = ConfigDict(extra="forbid")

    name: _Name
    address: _Address = None
    latitude: _Latitude = None
    longitude: _Longitude = None
    radius_m: Annotated[int, Field(ge=RADIUS_MIN_M, le=RADIUS_MAX_M)] = 100


class WorkplaceUpdate(BaseModel):
    """Only fields present are applied. Latitude and longitude go together (null clears both).
    `is_default: true` makes it the default (the previous one stops being it)."""

    model_config = ConfigDict(extra="forbid")

    name: _Name = None
    address: _Address = None
    latitude: _Latitude = None
    longitude: _Longitude = None
    radius_m: Annotated[
        int | None, Field(ge=RADIUS_MIN_M, le=RADIUS_MAX_M), AfterValidator(_required_int)
    ] = None
    is_default: Literal[True] | None = None


def _shift_name(value: str) -> str:
    value = _SPACES.sub(" ", value).strip()
    if not value:
        raise ValueError("Name is required")
    return value


ShiftName = Annotated[str, Field(max_length=50), AfterValidator(_shift_name)]


class ShiftIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: ShiftCode
    name_km: ShiftName
    name_en: ShiftName
    start_time: TimeIn
    end_time: TimeIn


def _both_shifts(value: list[ShiftIn]) -> list[ShiftIn]:
    if sorted(s.code for s in value) != ["afternoon", "morning"]:
        raise ValueError("Give both shifts (morning and afternoon) once each")
    return value


Targets = list[uuid.UUID] | Literal["all"]


def _targets(value: Targets) -> Targets:
    if isinstance(value, list):
        if not value:
            raise ValueError("Choose at least one workplace")
        return list(dict.fromkeys(value))
    return value


TargetsIn = Annotated[Targets, AfterValidator(_targets)]


def _weekdays(value: list[int]) -> list[int]:
    days = sorted(set(value))
    if not days:
        raise ValueError("Track at least one weekday")
    return days


class WeekdaysIn(BaseModel):
    """Tracked weekdays (Monday = 1 ... Sunday = 7) for these workplaces (or "all"), from
    `effective_from` (default today; not in the past)."""

    model_config = ConfigDict(extra="forbid")

    workplace_ids: TargetsIn
    weekdays: Annotated[list[Annotated[int, Field(ge=1, le=7)]], AfterValidator(_weekdays)]
    effective_from: date | None = None


class ShiftsIn(BaseModel):
    """Both shifts and the rules, validated together, for these workplaces (or "all"), from
    `effective_from` (default today; not in the past)."""

    model_config = ConfigDict(extra="forbid")

    workplace_ids: TargetsIn
    shifts: Annotated[list[ShiftIn], AfterValidator(_both_shifts)]
    open_before_min: Annotated[int, Field(gt=0, le=OPEN_BEFORE_MAX)]
    absent_after_min: Annotated[int, Field(gt=0, le=ABSENT_AFTER_MAX)]
    checkout_window_min: Annotated[int, Field(ge=0, le=CHECKOUT_WINDOW_MAX)]
    reminders_enabled: bool
    # Whether early check-ins / overtime count as extra time (records created from then on).
    count_early_checkin: bool
    count_overtime: bool
    effective_from: date | None = None


class SchedulingWorkplace(BaseModel):
    id: uuid.UUID
    name: str
    is_default: bool
    current: ScheduleOut
    upcoming: list[ScheduleOut]  # effective after today, soonest first


class SchedulingDiffers(BaseModel):
    """Whether the selected workplaces' current schedules differ (the page shows the first)."""

    weekdays: bool
    shifts: bool


class SchedulingOut(BaseModel):
    today: date
    timezone: str
    workplaces: list[SchedulingWorkplace]
    differs: SchedulingDiffers
    workplace_options: list[WorkplaceOption]


class SchedulingWriteOut(BaseModel):
    """The scheduling of the written workplaces, and how many records the change removed (a
    weekday made untracked from today) or brought back (absents recreated)."""

    scheduling: SchedulingOut
    records_removed: int
    absents_recreated: int
    skipped_locked: int = 0  # records / absents left alone: a pending / approved request


# --- Holidays and the calendar -------------------------------------------------------------------

HolidayName = Annotated[str, Field(max_length=HOLIDAY_NAME_MAX_LENGTH), AfterValidator(_shift_name)]
Year = Annotated[int, Field(ge=2000, le=2100)]


class HolidayIn(BaseModel):
    """A holiday (whole days, at most 31): every workplace (`all`, later ones too) or the
    `workplace_ids` given (`selected`)."""

    model_config = ConfigDict(extra="forbid")

    name_km: HolidayName
    name_en: HolidayName
    start_date: date
    end_date: date
    scope: Literal["all", "selected"]
    workplace_ids: list[uuid.UUID] | None = None
    note: Annotated[
        str | None, Field(max_length=HOLIDAY_NOTE_MAX_LENGTH), AfterValidator(_optional_text)
    ] = None


class HolidayBrief(BaseModel):
    id: uuid.UUID
    name_km: str
    name_en: str


class HolidayOut(HolidayBrief):
    start_date: date
    end_date: date
    days: int
    scope: Literal["all", "selected"]
    workplaces: list[UserWorkplace]  # `selected` only (empty for `all`)
    note: str | None
    created_by: UserRef | None
    created_at: datetime
    updated_by: UserRef | None
    updated_at: datetime


class HolidayWriteOut(BaseModel):
    holiday: HolidayOut | None  # null after a delete
    records_removed: int
    absents_recreated: int
    skipped_locked: int = 0


class HolidayCopyIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    from_year: Year
    to_year: Year


class HolidayCopyOut(BaseModel):
    created: list[HolidayOut]
    skipped: int  # already there (same name and dates)
    records_removed: int
    skipped_locked: int = 0


class DayOffOut(BaseModel):
    """Why a day isn't tracked: `holiday` (with the holidays) or `weekday`."""

    reason: Literal["holiday", "weekday"]
    holidays: list[HolidayBrief]


class CalendarWorkplaceDay(BaseModel):
    workplace_id: uuid.UUID
    day_off: DayOffOut | None


class CalendarDay(BaseModel):
    """`status`: `tracked` everywhere selected, `off` everywhere (`day_off`: the first
    workplace's reason), or `mixed`. `holidays`: those covering any selected workplace.
    `workplaces`: per workplace when several are selected."""

    date: date
    status: Literal["tracked", "off", "mixed"]
    day_off: DayOffOut | None
    holidays: list[HolidayBrief]
    workplaces: list[CalendarWorkplaceDay] | None


class CalendarOut(BaseModel):
    year: int
    month: int
    today: date
    workplaces: list[UserWorkplace]
    days: list[CalendarDay]


# --- Records -------------------------------------------------------------------------------------


class RecordOut(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    work_date: date
    shift_code: ShiftCode
    workplace_id: uuid.UUID | None
    scheduled_start: datetime
    scheduled_end: datetime
    status: RecordStatus
    late_minutes: int
    early_minutes: int
    overtime_minutes: int
    early_counts: bool
    overtime_counts: bool
    check_in_at: datetime | None
    check_in_distance_m: float | None
    check_in_accuracy_m: float | None
    checkout_status: CheckoutStatus | None
    check_out_at: datetime | None
    check_out_distance_m: float | None
    check_out_accuracy_m: float | None
    source: Literal["mini_app", "auto", "correction"]
    corrected: bool
    correction_reason: str | None
    corrected_by: UserRef | None
    corrected_at: datetime | None


class ShiftDayOut(BaseModel):
    """One shift on one day, with its windows as instants and (for one person) the record."""

    code: ShiftCode
    name_km: str
    name_en: str
    start: datetime
    end: datetime
    check_in_opens: datetime
    check_in_until: datetime
    check_out_opens: datetime
    check_out_until: datetime
    # upcoming | check_in_open | in_progress | check_out_open | closed
    phase: Literal["upcoming", "check_in_open", "in_progress", "check_out_open", "closed"]
    record: RecordOut | None = None


class NextActionOut(BaseModel):
    action: Literal["check_in", "check_out", "none"]
    shift_code: ShiftCode | None = None
    # The last minute of the open window ("until 07:44") and its exclusive end.
    until: datetime | None = None
    closes_at: datetime | None = None
    # When nothing is open: what opens next and when.
    next_action: Action | None = None
    next_shift_code: ShiftCode | None = None
    next_opens_at: datetime | None = None


class MeTodayOut(BaseModel):
    """On a day off `day_off` says why, `shifts` is empty and `next_action` is `none` with the
    next tracked opening."""

    server_time: datetime
    timezone: str
    work_date: date
    workplace: WorkplaceBrief | None
    day_off: DayOffOut | None
    shifts: list[ShiftDayOut]
    next_action: NextActionOut
    # `starts_on`: attendance begins on this date (before it nothing is asked); `tracked` false:
    # a supervisor whose attendance is switched off. Both come with `next_action = none`.
    tracked: bool = True
    starts_on: date | None = None


class LocationIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    latitude: Annotated[float, Field(ge=-90, le=90)]
    longitude: Annotated[float, Field(ge=-180, le=180)]
    accuracy_m: Annotated[float, Field(ge=0, le=100_000)]


class CheckResultOut(BaseModel):
    action: Action
    record: RecordOut
    today: MeTodayOut


# --- Day view ------------------------------------------------------------------------------------


class ShiftKpis(BaseModel):
    expected: int
    present: int
    late: int
    absent: int
    not_yet: int
    no_record: int
    checked_out: int
    forgot_checkout: int


class DayShiftOut(BaseModel):
    code: ShiftCode
    name_km: str
    name_en: str
    start: datetime
    end: datetime
    check_in_until: datetime
    check_out_until: datetime
    phase: Literal["upcoming", "check_in_open", "in_progress", "check_out_open", "closed"]
    kpis: ShiftKpis


class DayCell(BaseModel):
    """`record` is null without a record: `state` says whether it may still come (`not_yet`) or
    the day is off at the row's workplace (`day_off`; a kept corrected record is `recorded`)."""

    state: Literal["recorded", "not_yet", "no_record", "day_off"]
    record: RecordOut | None


class DayRow(BaseModel):
    user: UserRef
    role: Role
    position: str | None
    is_active: bool
    workplace: UserWorkplace | None
    day_off: DayOffOut | None
    shifts: dict[str, DayCell]
    # Rows of the "Starts later" group: the first tracked day.
    starts_on: date | None = None


class DayWorkplaceOut(BaseModel):
    """One workplace on that day: its shifts (its own times) with KPIs for its employees."""

    id: uuid.UUID
    name: str
    is_default: bool
    day_off: DayOffOut | None
    shifts: list[DayShiftOut]


class DayOut(BaseModel):
    """`shifts`: KPIs per shift over every row shown (times of the filtered workplace, else the
    default one); `workplaces`: the same per workplace; `workplace_options`: every active
    workplace (for the filter)."""

    date: date
    timezone: str
    server_time: datetime
    workplace_id: uuid.UUID | None
    day_off: DayOffOut | None  # of the filtered workplace, else the default one
    shifts: list[DayShiftOut]
    workplaces: list[DayWorkplaceOut]
    workplace_options: list[UserWorkplace]
    rows: list[DayRow]
    # Not expected that day and in no KPI: attendance starts later / a supervisor not tracked.
    # Their cells hold only records already made.
    starts_later: list[DayRow] = []
    not_tracked: list[DayRow] = []


# --- Corrections ---------------------------------------------------------------------------------

Reason = Annotated[str, Field(max_length=REASON_MAX_LENGTH), AfterValidator(_reason)]


class CorrectionIn(BaseModel):
    """`status` absent clears everything; otherwise `check_in_time` is required and present /
    late follows from it (late minutes from the record's snapshot start). `check_out_time`
    needs `checkout_status = checked_out` (implied when only the time is given)."""

    model_config = ConfigDict(extra="forbid")

    status: RecordStatus
    check_in_time: TimeIn | None = None
    check_out_time: TimeIn | None = None
    checkout_status: CheckoutStatus | None = None
    reason: Reason


class RecordCreateIn(CorrectionIn):
    user_id: uuid.UUID
    work_date: date
    shift_code: ShiftCode


class WorkplaceDeleteOut(BaseModel):
    """`archived` when the workplace has attendance history (records keep it), else `deleted`."""

    result: Literal["archived", "deleted"]


# --- Summary -------------------------------------------------------------------------------------


class SummaryPeriod(BaseModel):
    """`month` null: the whole year. `start` / `end`: the first and last day listed (`end` is
    at most today)."""

    year: int
    month: int | None
    start: date
    end: date


class SummaryEmployee(BaseModel):
    user: UserRef
    role: Role
    position: str | None
    is_active: bool
    workplace: UserWorkplace | None
    # The attendance start date (older accounts: the creation date in the business time zone):
    # earlier days aren't listed.
    since: date


class SummaryShift(BaseModel):
    """The employee's shifts (names from their workplace's schedule), in order."""

    code: ShiftCode
    name_km: str
    name_en: str


class SummaryShifts(BaseModel):
    total_shifts: int
    by_shift: dict[str, int]
    minutes: int


class SummaryCount(BaseModel):
    count: int
    minutes: int


class SummaryKpis(BaseModel):
    present: SummaryShifts
    absent: SummaryShifts
    late: SummaryCount
    early: SummaryCount
    overtime: SummaryCount
    missing_minutes: int
    extra_minutes: int
    balance_minutes: int  # extra - missing (signed)
    forgot_checkout: int


class SummaryDayShift(BaseModel):
    """`none`: no record (yet). The record carries the times, minutes and correction."""

    code: ShiftCode
    status: Literal["present", "late", "absent", "none"]
    record: RecordOut | None


class SummaryDay(BaseModel):
    """`day_off`: not tracked that day (its records, if any were kept, don't count)."""

    date: date
    day_off: DayOffOut | None
    shifts: list[SummaryDayShift]
    # Inside an untracked period: shown greyed, counted in no KPI.
    not_tracked: bool = False


class SummaryOut(BaseModel):
    timezone: str
    period: SummaryPeriod
    employee: SummaryEmployee
    shifts: list[SummaryShift]
    kpis: SummaryKpis
    days: list[SummaryDay]  # newest first
    # Monthly periods only: the month's request (if any), its eligibility (`eligible`,
    # `not_needed`, `window_not_open`, `window_closed`), and whether a pending / approved request
    # locks the month's records.
    request: RequestBrief | None = None
    request_eligibility: Eligibility | None = None
    month_locked: bool = False
