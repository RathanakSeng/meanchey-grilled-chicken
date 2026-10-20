"""Attendance requests: a month's missing time covered by a salary cut and / or unpaid extra work.

Minutes everywhere. `eligibility`: `eligible` (the window is open and the missing time is at least
an hour), `not_needed` (under an hour), `window_not_open` (the month hasn't ended) or
`window_closed` (after the deadline; with no request it reads "No request").
"""

import uuid
from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.attendance.requests import DEADLINE_DAY_MAX, DEADLINE_DAY_MIN, NOTE_MAX_LENGTH
from app.attendance.requests import REASON_MAX_LENGTH as REASON_MAX
from app.schemas.common import UserRef

RequestStatus = Literal["pending", "approved", "rejected"]
RequestType = Literal["salary_cut", "unpaid_work", "both"]
Eligibility = Literal["eligible", "not_needed", "window_not_open", "window_closed"]

Minutes = Annotated[int, Field(ge=0, le=100_000)]
Note = Annotated[str, Field(max_length=NOTE_MAX_LENGTH)]
Text = Annotated[str, Field(min_length=1, max_length=REASON_MAX)]


class RequestCreateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    year: Annotated[int, Field(ge=2000, le=2100)]
    month: Annotated[int, Field(ge=1, le=12)]
    salary_cut_minutes: Minutes
    unpaid_work_minutes: Minutes
    note: Note | None = None


class RequestApproveIn(BaseModel):
    """Both splits absent: approve as submitted. A split given (one or both; a missing one is
    the rest of the missing time) = approve with changes. `comment` is optional."""

    model_config = ConfigDict(extra="forbid")

    salary_cut_minutes: Minutes | None = None
    unpaid_work_minutes: Minutes | None = None
    comment: Annotated[str, Field(max_length=REASON_MAX)] | None = None


class RequestRejectIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: Text


class RequestSettingsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_deadline_day: Annotated[int, Field(ge=DEADLINE_DAY_MIN, le=DEADLINE_DAY_MAX)]


class RequestSettingsOut(BaseModel):
    request_deadline_day: int


class RequestBrief(BaseModel):
    """A request inside a summary or a month row."""

    id: uuid.UUID
    status: RequestStatus
    type: RequestType
    requested_salary_cut_minutes: int
    requested_unpaid_work_minutes: int
    approved_salary_cut_minutes: int | None
    approved_unpaid_work_minutes: int | None
    approved_with_changes: bool
    review_comment: str | None
    reject_reason: str | None
    submitted_at: datetime
    reviewed_by: UserRef | None
    reviewed_at: datetime | None


class RequestOut(RequestBrief):
    user: UserRef
    position: str | None
    year: int
    month: int
    missing_minutes: int
    extra_minutes: int
    absent_minutes: int
    late_minutes: int
    balance_minutes: int
    note: str | None
    month_locked: bool  # pending or approved


class MyRequestMonth(BaseModel):
    year: int
    month: int
    balance_minutes: int
    missing_minutes: int
    extra_minutes: int
    absent_minutes: int
    late_minutes: int
    eligibility: Eligibility
    opens: date
    closes: date
    request: RequestBrief | None


class MyRequestsOut(BaseModel):
    """The months of the year (newest first, up to the current month, from the month attendance
    started) with their state."""

    timezone: str
    year: int
    request_deadline_day: int
    months: list[MyRequestMonth]


class RequestRow(BaseModel):
    """A list row: a request, or (`status = no_request`) an eligible month nobody requested."""

    id: uuid.UUID | None
    status: Literal["pending", "approved", "rejected", "no_request"]
    user: UserRef
    position: str | None
    year: int
    month: int
    type: RequestType | None
    missing_minutes: int
    requested_salary_cut_minutes: int | None
    requested_unpaid_work_minutes: int | None
    approved_salary_cut_minutes: int | None
    approved_unpaid_work_minutes: int | None
    approved_with_changes: bool
    note: str | None
    submitted_at: datetime | None


class RequestPage(BaseModel):
    items: list[RequestRow]
    total: int
    page: int
    page_size: int
    pending_count: int  # in the viewer's scope
