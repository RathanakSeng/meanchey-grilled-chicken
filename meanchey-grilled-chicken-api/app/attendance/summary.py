"""Attendance summary as pure functions: the period and the KPIs over a list of records.

Every number comes from the record itself (its snapshot times and stored minutes), so a later
schedule change never rewrites the past and corrected records count with their corrected values:

- scheduled minutes = scheduled_end - scheduled_start
- **present** = present + late records; present minutes = sum(scheduled - late + early + overtime)
- **absent** = absent records; absent minutes = their scheduled minutes
- **late** = late records, sum(late_minutes); **early** / **overtime** = records with minutes > 0
- missing = absent + late minutes; extra = early + overtime minutes; balance = extra - missing
- forgot check-out = records with `checkout_status = forgot_checkout`
"""

import calendar
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Protocol

MIN_YEAR = 2000


class SummaryRecord(Protocol):
    shift_code: str
    status: str
    scheduled_start: datetime
    scheduled_end: datetime
    late_minutes: int
    early_minutes: int
    overtime_minutes: int
    checkout_status: str | None


@dataclass(frozen=True)
class Period:
    year: int
    month: int | None  # None: the whole year
    start: date
    end: date  # the last day shown: the period's last day, at most today


class PeriodError(ValueError):
    def __init__(self, field_name: str, message: str) -> None:
        super().__init__(message)
        self.field = field_name


def period(year: int | None, month: int | None, today: date) -> Period:
    """No year and no month: the current month; a year without a month: that whole year; a month
    without a year: that month this year. Future periods are refused."""
    if year is None and month is None:
        year, month = today.year, today.month
    elif year is None:
        year = today.year
    assert year is not None
    if year < MIN_YEAR or year > today.year:
        raise PeriodError("year", f"The year must be between {MIN_YEAR} and {today.year}")
    if month is not None and not 1 <= month <= 12:
        raise PeriodError("month", "The month must be between 1 and 12")
    if month is None:
        start, last = date(year, 1, 1), date(year, 12, 31)
    else:
        start = date(year, month, 1)
        last = date(year, month, calendar.monthrange(year, month)[1])
    if start > today:
        raise PeriodError("month", "The period can't be in the future")
    return Period(year, month, start, min(last, today))


def scheduled_minutes(r: SummaryRecord) -> int:
    return max(0, round((r.scheduled_end - r.scheduled_start).total_seconds() / 60))


@dataclass
class Count:
    count: int = 0
    minutes: int = 0

    def add(self, minutes: int) -> None:
        if minutes > 0:
            self.count += 1
            self.minutes += minutes


@dataclass
class Shifts:
    total_shifts: int = 0
    by_shift: dict[str, int] = field(default_factory=dict)
    minutes: int = 0

    def add(self, code: str, minutes: int) -> None:
        self.total_shifts += 1
        self.by_shift[code] = self.by_shift.get(code, 0) + 1
        self.minutes += minutes


@dataclass
class Kpis:
    present: Shifts
    absent: Shifts
    late: Count
    early: Count
    overtime: Count
    forgot_checkout: int = 0

    @property
    def missing_minutes(self) -> int:
        return self.absent.minutes + self.late.minutes

    @property
    def extra_minutes(self) -> int:
        return self.early.minutes + self.overtime.minutes

    @property
    def balance_minutes(self) -> int:
        return self.extra_minutes - self.missing_minutes


def kpis(records: Iterable[SummaryRecord], shift_codes: Sequence[str]) -> Kpis:
    """KPIs over recorded shifts; `by_shift` has every code in `shift_codes` (0 when none)."""
    out = Kpis(
        present=Shifts(by_shift=dict.fromkeys(shift_codes, 0)),
        absent=Shifts(by_shift=dict.fromkeys(shift_codes, 0)),
        late=Count(),
        early=Count(),
        overtime=Count(),
    )
    for r in records:
        scheduled = scheduled_minutes(r)
        if r.status == "absent":
            out.absent.add(r.shift_code, scheduled)
            continue
        out.present.add(
            r.shift_code,
            max(0, scheduled - r.late_minutes + r.early_minutes + r.overtime_minutes),
        )
        if r.status == "late":
            out.late.count += 1
            out.late.minutes += r.late_minutes
        out.early.add(r.early_minutes)
        out.overtime.add(r.overtime_minutes)
        if r.checkout_status == "forgot_checkout":
            out.forgot_checkout += 1
    return out
