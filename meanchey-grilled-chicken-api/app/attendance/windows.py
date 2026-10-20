"""Attendance rules as pure functions: windows, decisions, next action, late minutes, distance.

Every window is derived from a shift's start / end (local time in BUSINESS_TIMEZONE) and three
settings. Closing times are **exclusive**:

    check-in   [start - open_before, start + absent_after)      morning: 06:30 – 07:44:59
    check-out  [end, end + checkout_window + 1 min)              morning: 12:00 – 12:59:59

so "until 07:44" / "until 12:59" (closing time minus one minute) is what people read, the
morning becomes absent at 07:45 and "forgot check-out" at 13:00.
"""

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Literal, Protocol
from zoneinfo import ZoneInfo

EARTH_RADIUS_M = 6_371_008.8
ONE_MINUTE = timedelta(minutes=1)
DAY_START = time(0, 0)


@dataclass(frozen=True)
class ShiftDef:
    code: str
    name_km: str
    name_en: str
    start: time
    end: time
    position: int


@dataclass(frozen=True)
class Rules:
    open_before_min: int
    absent_after_min: int
    checkout_window_min: int
    max_accuracy_m: int
    reminders_enabled: bool = True
    count_early_checkin: bool = True
    count_overtime: bool = True


@dataclass(frozen=True)
class ShiftWindows:
    shift: ShiftDef
    work_date: date
    start: datetime
    end: datetime
    check_in_opens: datetime
    check_in_closes: datetime  # exclusive: from here the shift is absent
    check_out_opens: datetime
    check_out_closes: datetime  # exclusive: from here an open record is "forgot check-out"

    @property
    def code(self) -> str:
        return self.shift.code


def local(day: date, t: time, tz: ZoneInfo) -> datetime:
    return datetime.combine(day, t, tzinfo=tz)


def shift_windows(shift: ShiftDef, rules: Rules, day: date, tz: ZoneInfo) -> ShiftWindows:
    start = local(day, shift.start, tz)
    end = local(day, shift.end, tz)
    return ShiftWindows(
        shift=shift,
        work_date=day,
        start=start,
        end=end,
        check_in_opens=start - timedelta(minutes=rules.open_before_min),
        check_in_closes=start + timedelta(minutes=rules.absent_after_min),
        check_out_opens=end,
        check_out_closes=end + timedelta(minutes=rules.checkout_window_min) + ONE_MINUTE,
    )


def day_windows(
    shifts: Sequence[ShiftDef], rules: Rules, day: date, tz: ZoneInfo
) -> list[ShiftWindows]:
    return sorted(
        (shift_windows(s, rules, day, tz) for s in shifts), key=lambda w: (w.start, w.code)
    )


def work_date(now: datetime, tz: ZoneInfo) -> date:
    return now.astimezone(tz).date()


def shown_until(closes: datetime) -> datetime:
    """The last minute people can act in ("until 07:44" for a window closing at 07:45)."""
    return closes - ONE_MINUTE


def late_minutes(check_in: datetime, start: datetime) -> int:
    """Whole minutes after the start (07:00:59 → 0, present; 07:01 → 1)."""
    seconds = (check_in - start).total_seconds()
    return max(0, math.floor(seconds / 60))


def early_minutes(check_in: datetime, start: datetime, limit: int) -> int:
    """Whole minutes before the start, from the check-in minute people read (06:40:30 → 20 for
    07:00), at most `limit` (the open-before window)."""
    minute = check_in.replace(second=0, microsecond=0)
    return max(0, min(limit, math.floor((start - minute).total_seconds() / 60)))


def overtime_minutes(check_out: datetime | None, end: datetime, limit: int) -> int:
    """Whole minutes after the end (12:25:40 → 25 for 12:00), at most `limit` (the check-out
    window); no check-out → 0."""
    if check_out is None:
        return 0
    return max(0, min(limit, math.floor((check_out - end).total_seconds() / 60)))


def haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance in metres."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(a)))


# --- Decisions -----------------------------------------------------------------------------------

CheckInKind = Literal["open", "too_early", "closed", "no_shift"]
CheckOutKind = Literal["open", "too_early", "closed"]


@dataclass(frozen=True)
class CheckInDecision:
    kind: CheckInKind
    window: ShiftWindows | None  # the open (or closed) shift
    next_window: ShiftWindows | None = None  # the next check-in window to open


@dataclass(frozen=True)
class CheckOutDecision:
    kind: CheckOutKind
    window: ShiftWindows


def _next_check_in(
    today: Sequence[ShiftWindows], tomorrow: Sequence[ShiftWindows], now: datetime
) -> ShiftWindows | None:
    for w in today:
        if w.check_in_opens > now:
            return w
    return tomorrow[0] if tomorrow else None


def decide_check_in(
    today: Sequence[ShiftWindows], tomorrow: Sequence[ShiftWindows], now: datetime
) -> CheckInDecision:
    """Which check-in window `now` falls in (the windows never overlap, see validate)."""
    for w in today:
        if w.check_in_opens <= now < w.check_in_closes:
            return CheckInDecision("open", w)
    nxt = _next_check_in(today, tomorrow, now)
    if not today or now < today[0].check_in_opens:
        return CheckInDecision("too_early", None, nxt)
    for w in today:
        # After the cutoff, until the shift ends: this shift's check-in is closed (absent).
        if w.check_in_closes <= now < w.end:
            return CheckInDecision("closed", w, nxt)
    return CheckInDecision("no_shift", None, nxt)


def decide_check_out(today: Sequence[ShiftWindows], now: datetime) -> CheckOutDecision | None:
    """Which check-out window `now` falls in, else the shift it is too early / too late for."""
    if not today:
        return None
    for w in today:
        if w.check_out_opens <= now < w.check_out_closes:
            return CheckOutDecision("open", w)
    for w in today:
        if w.check_in_opens <= now < w.end:
            return CheckOutDecision("too_early", w)
    if now < today[0].check_in_opens:
        return CheckOutDecision("too_early", today[0])
    closed = [w for w in today if w.check_out_closes <= now]
    return CheckOutDecision("closed", closed[-1] if closed else today[-1])


class RecordState(Protocol):
    status: str
    check_in_at: datetime | None
    checkout_status: str | None


def is_open(record: RecordState | None) -> bool:
    """Checked in and not checked out (nor marked forgot)."""
    return (
        record is not None
        and record.check_in_at is not None
        and record.status != "absent"
        and record.checkout_status is None
    )


@dataclass(frozen=True)
class NextAction:
    action: Literal["check_in", "check_out", "none"]
    window: ShiftWindows | None = None
    until: datetime | None = None  # exclusive end of the open window
    # When nothing is open: the next thing that will open.
    next_action: Literal["check_in", "check_out"] | None = None
    next_window: ShiftWindows | None = None
    next_opens_at: datetime | None = None


def next_action(
    today: Sequence[ShiftWindows],
    tomorrow: Sequence[ShiftWindows],
    records: Mapping[str, RecordState],
    now: datetime,
) -> NextAction:
    """The one thing to do now. A pending check-out comes before a check-in (12:30–12:59: the
    morning check-out first, then the afternoon check-in)."""
    for w in today:
        if w.check_out_opens <= now < w.check_out_closes and is_open(records.get(w.code)):
            return NextAction("check_out", w, w.check_out_closes)
    for w in today:
        if w.check_in_opens <= now < w.check_in_closes and records.get(w.code) is None:
            return NextAction("check_in", w, w.check_in_closes)
    events: list[tuple[datetime, Literal["check_in", "check_out"], ShiftWindows]] = []
    for w in today:
        record = records.get(w.code)
        if record is None and w.check_in_opens > now:
            events.append((w.check_in_opens, "check_in", w))
        if is_open(record) and w.check_out_opens > now:
            events.append((w.check_out_opens, "check_out", w))
    if not events and tomorrow:
        events.append((tomorrow[0].check_in_opens, "check_in", tomorrow[0]))
    if not events:
        return NextAction("none")
    at, kind, w = min(events, key=lambda e: e[0])
    return NextAction("none", next_action=kind, next_window=w, next_opens_at=at)


# --- Validation ----------------------------------------------------------------------------------


def _minutes(t: time) -> int:
    return t.hour * 60 + t.minute


def validate(shifts: Sequence[ShiftDef], rules: Rules) -> list[tuple[list[str], str]]:
    """Problems as (loc, message); empty when the shifts and rules make a valid day."""
    problems: list[tuple[list[str], str]] = []
    ordered = sorted(shifts, key=lambda s: _minutes(s.start))
    for s in ordered:
        loc = ["body", "shifts", s.code]
        start, end = _minutes(s.start), _minutes(s.end)
        if start >= end:
            problems.append(([*loc, "end_time"], "The shift must end after it starts"))
            continue
        if start - rules.open_before_min < 0:
            problems.append(([*loc, "start_time"], "The check-in window starts before midnight"))
        if end + rules.checkout_window_min + 1 > 24 * 60:
            problems.append(([*loc, "end_time"], "The check-out window ends after midnight"))
        if start + rules.absent_after_min > end:
            problems.append(
                (["body", "absent_after_min"], "Check-in must close by the end of the shift")
            )
    for prev, nxt in zip(ordered, ordered[1:], strict=False):
        loc = ["body", "shifts", nxt.code, "start_time"]
        if _minutes(nxt.start) < _minutes(prev.end):
            problems.append((loc, "Shifts must not overlap"))
        elif _minutes(nxt.start) - rules.open_before_min < _minutes(prev.start) + (
            rules.absent_after_min
        ):
            problems.append((loc, "Two check-in windows overlap"))
        elif _minutes(nxt.end) < _minutes(prev.end) + rules.checkout_window_min + 1:
            problems.append((loc, "Two check-out windows overlap"))
    return problems
