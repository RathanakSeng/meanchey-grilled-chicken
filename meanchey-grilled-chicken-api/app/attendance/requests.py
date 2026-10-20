"""Monthly missing-time requests as pure functions: eligibility, the submission window, the split.

After a month ends, a tracked employee whose **missing time is at least 1 hour** sends one request
saying how it will be covered: a salary cut, unpaid extra work, or both. The missing time is the
month's `balance_minutes` when negative (missing - extra), as a positive number.

- **Window:** from the 1st of the following month until the deadline day of that month (inclusive,
  `request_deadline_day`, default 7), in the business time zone.
- **Eligibility** of a month: `window_not_open` (the month hasn't ended), `not_needed` (under an
  hour), `eligible` (window open) or `window_closed` (after the deadline).
"""

import calendar
from dataclasses import dataclass
from datetime import date
from typing import Literal

MIN_MISSING_MINUTES = 60
DEFAULT_DEADLINE_DAY = 7
DEADLINE_DAY_MIN = 1
DEADLINE_DAY_MAX = 28
NOTE_MAX_LENGTH = 500
REASON_MAX_LENGTH = 500

Eligibility = Literal["eligible", "not_needed", "window_not_open", "window_closed"]
RequestType = Literal["salary_cut", "unpaid_work", "both"]


@dataclass(frozen=True)
class Window:
    opens: date  # the 1st of the following month
    closes: date  # the deadline day of the following month (inclusive)


def window(year: int, month: int, deadline_day: int) -> Window:
    ny, nm = (year + 1, 1) if month == 12 else (year, month + 1)
    last = calendar.monthrange(ny, nm)[1]
    return Window(date(ny, nm, 1), date(ny, nm, min(deadline_day, last)))


def month_end(year: int, month: int) -> date:
    return date(year, month, calendar.monthrange(year, month)[1])


def missing_minutes(balance_minutes: int) -> int:
    """The month's missing time for a request: the negative balance, as a positive number."""
    return max(0, -balance_minutes)


def eligibility(
    year: int, month: int, balance_minutes: int, deadline_day: int, today: date
) -> Eligibility:
    w = window(year, month, deadline_day)
    if today < w.opens:
        return "window_not_open"
    if missing_minutes(balance_minutes) < MIN_MISSING_MINUTES:
        return "not_needed"
    if today > w.closes:
        return "window_closed"
    return "eligible"


def request_type(salary_cut_minutes: int, unpaid_work_minutes: int) -> RequestType:
    if salary_cut_minutes > 0 and unpaid_work_minutes > 0:
        return "both"
    return "salary_cut" if salary_cut_minutes > 0 else "unpaid_work"


def split_matches(salary_cut_minutes: int, unpaid_work_minutes: int, missing: int) -> bool:
    return (
        salary_cut_minutes >= 0
        and unpaid_work_minutes >= 0
        and (salary_cut_minutes + unpaid_work_minutes == missing)
    )
