"""An employee's own schedule on top of their workplace's: override versions and holiday
exceptions, as pure functions (the loading and the per-date resolution live in
`app.attendance.days`).

    holidays (all / selected workplaces)
     → the workplace's schedule version for the date   (weekdays, shifts, rules)
     → the employee's override version for the date    (only the fields set; the rest inherits)
     → a holiday exception for the employee and date   (works on that holiday day)
     = the employee's shifts and times that day        (the rules always from the workplace)

Override fields (null = inherit): `weekdays`, `shift_codes` (which of the workplace's shifts),
`shift_times` (`{code: {start_time, end_time}}`). The windows always derive from the workplace's
rules applied to the employee's own start / end.
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import replace
from datetime import date, datetime
from typing import Any, Literal

from app.attendance import windows as win
from app.attendance.workplaces import parse_hm
from app.models import AttendanceEmployeeOverride, AttendanceHolidayException

Field = Literal["weekdays", "shift_codes", "shift_times"]
FIELDS: tuple[Field, ...] = ("weekdays", "shift_codes", "shift_times")
INHERIT = "inherit"


def override_on(
    versions: Sequence[AttendanceEmployeeOverride], day: date
) -> AttendanceEmployeeOverride | None:
    """The employee's version in effect on `day` (`versions` sorted by `effective_from`); none
    before the first (unlike a workplace's, an employee's schedule simply inherits then)."""
    found = None
    for v in versions:
        if v.effective_from <= day:
            found = v
        else:
            break
    return found


def custom_fields(o: AttendanceEmployeeOverride | None) -> list[Field]:
    if o is None:
        return []
    return [f for f in FIELDS if getattr(o, f) is not None]


def with_times(d: win.ShiftDef, times: Mapping[str, Any] | None) -> win.ShiftDef:
    t = (times or {}).get(d.code)
    if not t:
        return d
    return replace(d, start=parse_hm(t["start_time"]), end=parse_hm(t["end_time"]))


def shift_defs(
    base: Sequence[win.ShiftDef],
    codes: Iterable[str] | None,
    times: Mapping[str, Any] | None,
) -> list[win.ShiftDef]:
    """The workplace's shifts narrowed to `codes` (null, or nothing left = all of them) with the
    times of `times` where given."""
    picked = set(codes or ())
    chosen = [d for d in base if d.code in picked] or list(base)
    return [with_times(d, times) for d in chosen]


def personal_defs(
    base: Sequence[win.ShiftDef], o: AttendanceEmployeeOverride | None
) -> list[win.ShiftDef]:
    """The employee's shifts on a working day (ignoring weekdays and holidays)."""
    if o is None:
        return list(base)
    return shift_defs(base, o.shift_codes, o.shift_times)


def exception_defs(
    normal: Sequence[win.ShiftDef],
    base: Sequence[win.ShiftDef],
    e: AttendanceHolidayException,
) -> list[win.ShiftDef]:
    """The shifts of a holiday exception: its own codes / times, else the employee's normal
    ones."""
    by_code = {d.code: d for d in normal}
    codes = e.shift_codes or [d.code for d in normal]
    chosen = [by_code.get(d.code, d) for d in base if d.code in codes] or list(normal)
    return [with_times(d, e.shift_times) for d in chosen]


def opened_before(
    defs: Sequence[win.ShiftDef], rules: win.Rules, day: date, at: datetime, tz: Any
) -> list[win.ShiftDef]:
    """Of `defs` on `day`, the shifts whose check-in window had opened by `at`."""
    return [w.shift for w in win.day_windows(defs, rules, day, tz) if w.check_in_opens <= at]


def times_of(defs: Iterable[win.ShiftDef]) -> dict[str, dict[str, str]]:
    return {
        d.code: {"start_time": d.start.strftime("%H:%M"), "end_time": d.end.strftime("%H:%M")}
        for d in defs
    }
