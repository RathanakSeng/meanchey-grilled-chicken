"""Employees' own schedules (override versions) and holiday work exceptions."""

import uuid
from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

from app.models import Role
from app.schemas.attendance import (
    DayOffOut,
    HolidayBrief,
    RulesOut,
    ShiftCode,
    ShiftWindowsOut,
    TimeHM,
    TimeIn,
    UserWorkplace,
)
from app.schemas.common import UserRef

ScheduleField = Literal["weekdays", "shift_codes", "shift_times"]
Inherit = Literal["inherit"]
UserIds = Annotated[list[uuid.UUID], Field(min_length=1, max_length=200)]


def _weekdays(value: list[int]) -> list[int]:
    days = sorted(set(value))
    if not days:
        raise ValueError("Pick at least one weekday")
    return days


def _codes(value: list[str]) -> list[str]:
    codes = [c for c in ("morning", "afternoon") if c in value]
    if not codes:
        raise ValueError("Pick at least one shift")
    return codes


Weekdays = Annotated[list[Annotated[int, Field(ge=1, le=7)]], AfterValidator(_weekdays)]
ShiftCodes = Annotated[list[ShiftCode], Field(min_length=1, max_length=2), AfterValidator(_codes)]


class ShiftTimeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start_time: TimeIn
    end_time: TimeIn


ShiftTimes = dict[ShiftCode, ShiftTimeIn]


class EmployeeScheduleIn(BaseModel):
    """For each of `user_ids`, a version from `effective_from` (default today; not in the
    past). Per field: missing = keep the value in effect then, `"inherit"` = the workplace's,
    else the employee's own value. `shift_times` holds only the shifts whose times differ."""

    model_config = ConfigDict(extra="forbid")

    user_ids: UserIds
    effective_from: date | None = None
    weekdays: Weekdays | Inherit = None  # type: ignore[assignment]
    shift_codes: ShiftCodes | Inherit = None  # type: ignore[assignment]
    shift_times: ShiftTimes | Inherit = None  # type: ignore[assignment]

    @model_validator(mode="after")
    def _something(self) -> "EmployeeScheduleIn":
        if not {"weekdays", "shift_codes", "shift_times"} & self.model_fields_set:
            raise ValueError("Change at least one of weekdays, shift_codes or shift_times")
        return self


class EmployeeResetIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_ids: UserIds
    effective_from: date | None = None


class ShiftTimeOut(BaseModel):
    start_time: TimeHM
    end_time: TimeHM


class PersonalShiftOut(BaseModel):
    code: ShiftCode
    name_km: str
    name_en: str
    start_time: TimeHM
    end_time: TimeHM
    windows: ShiftWindowsOut


class ScheduleSummaryOut(BaseModel):
    """An employee's schedule on a date: weekdays (Monday = 1), the shifts they work with their
    times, and which fields are their own (`custom`, else the workplace's)."""

    weekdays: list[int]
    shifts: list[PersonalShiftOut]
    custom: list[ScheduleField]


class OverrideVersionOut(BaseModel):
    """An override version; a null field inherits the workplace's."""

    id: uuid.UUID
    effective_from: date
    weekdays: list[int] | None
    shift_codes: list[ShiftCode] | None
    shift_times: dict[ShiftCode, ShiftTimeOut] | None
    created_by: UserRef | None
    created_at: datetime


class EmployeeScheduleRow(BaseModel):
    user: UserRef
    role: Role
    position: str | None
    workplace: UserWorkplace | None
    summary: ScheduleSummaryOut  # in effect today
    upcoming: int  # upcoming versions
    next_change: date | None


class EmployeeScheduleList(BaseModel):
    today: date
    items: list[EmployeeScheduleRow]
    workplace_options: list[UserWorkplace]


class PreviewShift(BaseModel):
    code: ShiftCode
    start_time: TimeHM
    end_time: TimeHM


class PreviewDay(BaseModel):
    """One day: the shifts the employee works, or why it's off; `works_on_holiday` when a
    holiday exception makes them work."""

    date: date
    shifts: list[PreviewShift]
    day_off: DayOffOut | None
    works_on_holiday: HolidayBrief | None


class EmployeeScheduleDetail(BaseModel):
    """`schedule`: the employee's schedule today; `workplace_schedule`: what they inherit (the
    workplace's today); `current`: the override version in effect (null = none);
    `upcoming`: later versions; `preview`: 7 days from `from`."""

    user: UserRef
    role: Role
    position: str | None
    workplace: UserWorkplace | None
    today: date
    schedule: ScheduleSummaryOut
    workplace_schedule: ScheduleSummaryOut
    rules: RulesOut
    current: OverrideVersionOut | None
    upcoming: list[OverrideVersionOut]
    preview: list[PreviewDay]


class EmployeeScheduleWriteOut(BaseModel):
    """`changed`: employees who got a version; `unchanged`: those already set that way."""

    effective_from: date
    changed: list[uuid.UUID]
    unchanged: list[uuid.UUID]


class HolidayExceptionIn(BaseModel):
    """`user_ids` work on `dates` (inside the holiday, today or later) with `shift_codes` /
    `shift_times` (null = their normal shifts and times)."""

    model_config = ConfigDict(extra="forbid")

    user_ids: UserIds
    dates: Annotated[list[date], Field(min_length=1, max_length=31)]
    shift_codes: ShiftCodes | None = None
    shift_times: ShiftTimes | None = None


class HolidayExceptionOut(BaseModel):
    id: uuid.UUID
    holiday_id: uuid.UUID
    user: UserRef
    role: Role
    date: date
    shift_codes: list[ShiftCode] | None
    shift_times: dict[ShiftCode, ShiftTimeOut] | None
    shifts: list[PreviewShift]  # what they work that day
    created_by: UserRef | None
    created_at: datetime


class HolidayExceptionsOut(BaseModel):
    items: list[HolidayExceptionOut]


class HolidayExceptionWriteOut(BaseModel):
    items: list[HolidayExceptionOut]
    records_removed: int = 0
    skipped_locked: int = 0
