"""Attendance rules as pure functions (app/attendance/windows.py): windows, decisions, the next
action through a whole day, late minutes, distance and settings validation."""

from dataclasses import dataclass
from datetime import date, time, timedelta

import pytest

from app.attendance import windows as win
from app.config import get_settings
from tests.conftest import at

TZ = get_settings().business_tz
DAY = date(2026, 10, 13)
SHIFTS = [
    win.ShiftDef("morning", "វេនព្រឹក", "Morning shift", time(7), time(12), 1),
    win.ShiftDef("afternoon", "វេនរសៀល", "Afternoon shift", time(13), time(15), 2),
]
RULES = win.Rules(open_before_min=30, absent_after_min=45, checkout_window_min=59)


def _days(rules: win.Rules = RULES, shifts=SHIFTS):
    return (
        win.day_windows(shifts, rules, DAY, TZ),
        win.day_windows(shifts, rules, DAY + timedelta(days=1), TZ),
    )


def _hm(value) -> str:
    return value.astimezone(TZ).strftime("%H:%M")


def test_default_windows() -> None:
    morning, afternoon = _days()[0]
    assert (_hm(morning.check_in_opens), _hm(morning.check_in_closes)) == ("06:30", "07:45")
    assert _hm(win.shown_until(morning.check_in_closes)) == "07:44"
    assert (_hm(morning.check_out_opens), _hm(morning.check_out_closes)) == ("12:00", "13:00")
    assert _hm(win.shown_until(morning.check_out_closes)) == "12:59"
    assert (_hm(afternoon.check_in_opens), _hm(afternoon.check_in_closes)) == ("12:30", "13:45")
    assert (_hm(afternoon.check_out_opens), _hm(afternoon.check_out_closes)) == ("15:00", "16:00")


def test_windows_follow_changed_times_and_rules() -> None:
    rules = win.Rules(15, 20, 30, 50)
    shifts = [
        win.ShiftDef("morning", "", "", time(8), time(11, 30), 1),
        win.ShiftDef("afternoon", "", "", time(14), time(17), 2),
    ]
    morning, afternoon = _days(rules, shifts)[0]
    assert _hm(morning.check_in_opens) == "07:45"
    assert _hm(morning.check_in_closes) == "08:20"
    assert _hm(morning.check_out_closes) == "12:01"  # until 12:00 (30 + the closing minute)
    assert _hm(afternoon.check_in_opens) == "13:45"


@pytest.mark.parametrize(
    ("hm", "kind", "shift", "next_shift"),
    [
        ("05:00", "too_early", None, "morning"),
        ("06:29:59", "too_early", None, "morning"),
        ("06:30", "open", "morning", None),
        ("07:00", "open", "morning", None),
        ("07:44:59", "open", "morning", None),
        ("07:45", "closed", "morning", "afternoon"),
        ("11:59", "closed", "morning", "afternoon"),
        ("12:00", "no_shift", None, "afternoon"),
        ("12:29", "no_shift", None, "afternoon"),
        ("12:30", "open", "afternoon", None),
        ("13:44:59", "open", "afternoon", None),
        ("13:45", "closed", "afternoon", "morning"),  # next: tomorrow's morning
        ("15:00", "no_shift", None, "morning"),
        ("23:59", "no_shift", None, "morning"),
    ],
)
def test_check_in_decision(hm, kind, shift, next_shift) -> None:
    today, tomorrow = _days()
    d = win.decide_check_in(today, tomorrow, at(hm))
    assert d.kind == kind
    assert (d.window.code if d.window else None) == shift
    if kind != "open":
        assert d.next_window is not None and d.next_window.code == next_shift
    if kind in ("closed", "no_shift") and hm >= "13:45":
        assert d.next_window.work_date == DAY + timedelta(days=1)


@pytest.mark.parametrize(
    ("hm", "kind", "shift"),
    [
        ("05:00", "too_early", "morning"),
        ("07:10", "too_early", "morning"),
        ("11:59:59", "too_early", "morning"),
        ("12:00", "open", "morning"),
        ("12:59:59", "open", "morning"),
        ("13:00", "too_early", "afternoon"),
        ("14:59", "too_early", "afternoon"),
        ("15:00", "open", "afternoon"),
        ("15:59", "open", "afternoon"),
        ("16:00", "closed", "afternoon"),
    ],
)
def test_check_out_decision(hm, kind, shift) -> None:
    d = win.decide_check_out(_days()[0], at(hm))
    assert d is not None
    assert (d.kind, d.window.code) == (kind, shift)


@dataclass
class Rec:
    status: str = "present"
    check_in_at: object = "x"
    checkout_status: str | None = None


ABSENT = Rec(status="absent", check_in_at=None)
OUT = Rec(checkout_status="checked_out")


@pytest.mark.parametrize(
    ("hm", "records", "expected"),
    [
        # Before anything opens: next is the morning check-in at 06:30.
        ("05:00", {}, ("none", None, "check_in", "morning", "06:30")),
        ("06:30", {}, ("check_in", "morning", None, None, None)),
        ("07:44", {}, ("check_in", "morning", None, None, None)),
        # Checked in: next is the morning check-out at 12:00.
        ("07:10", {"morning": Rec()}, ("none", None, "check_out", "morning", "12:00")),
        # Absent (07:45–11:59): next is the afternoon check-in.
        ("08:00", {"morning": ABSENT}, ("none", None, "check_in", "afternoon", "12:30")),
        ("12:00", {"morning": Rec()}, ("check_out", "morning", None, None, None)),
        ("12:10", {"morning": OUT}, ("none", None, "check_in", "afternoon", "12:30")),
        # The overlap: the morning check-out first, then the afternoon check-in.
        ("12:40", {"morning": Rec()}, ("check_out", "morning", None, None, None)),
        ("12:40", {"morning": OUT}, ("check_in", "afternoon", None, None, None)),
        ("12:40", {"morning": ABSENT}, ("check_in", "afternoon", None, None, None)),
        # 13:00: the morning check-out closed (forgot); the afternoon check-in still open.
        ("13:00", {"morning": Rec()}, ("check_in", "afternoon", None, None, None)),
        (
            "13:10",
            {"morning": OUT, "afternoon": Rec()},
            ("none", None, "check_out", "afternoon", "15:00"),
        ),
        (
            "15:30",
            {"morning": OUT, "afternoon": Rec()},
            ("check_out", "afternoon", None, None, None),
        ),
        # After 15:59 (or all done): tomorrow's morning check-in.
        (
            "16:00",
            {"morning": OUT, "afternoon": Rec()},
            ("none", None, "check_in", "morning", "06:30"),
        ),
        (
            "15:30",
            {"morning": OUT, "afternoon": OUT},
            ("none", None, "check_in", "morning", "06:30"),
        ),
    ],
)
def test_next_action_through_the_day(hm, records, expected) -> None:
    today, tomorrow = _days()
    na = win.next_action(today, tomorrow, records, at(hm))
    got = (
        na.action,
        na.window.code if na.window else None,
        na.next_action,
        na.next_window.code if na.next_window else None,
        _hm(na.next_opens_at) if na.next_opens_at else None,
    )
    assert got == expected


def test_next_action_until_is_the_window_end() -> None:
    today, tomorrow = _days()
    na = win.next_action(today, tomorrow, {}, at("06:40"))
    assert _hm(win.shown_until(na.until)) == "07:44"
    na = win.next_action(today, tomorrow, {"morning": Rec()}, at("12:05"))
    assert _hm(win.shown_until(na.until)) == "12:59"


@pytest.mark.parametrize(
    ("hm", "minutes"),
    [("06:45", 0), ("07:00", 0), ("07:00:59", 0), ("07:01", 1), ("07:12:30", 12), ("07:44", 44)],
)
def test_late_minutes(hm, minutes) -> None:
    assert win.late_minutes(at(hm), at("07:00")) == minutes


def test_haversine() -> None:
    assert win.haversine_m(11.5, 104.9, 11.5, 104.9) == 0
    # 0.001° of latitude ≈ 111.2 m.
    assert win.haversine_m(11.5, 104.9, 11.501, 104.9) == pytest.approx(111.19, abs=0.05)
    # Phnom Penh → Siem Reap, about 233 km.
    assert win.haversine_m(11.5564, 104.9282, 13.3633, 103.8564) == pytest.approx(233_000, rel=0.02)


def _problems(shifts, rules=RULES) -> list[str]:
    return [msg for _, msg in win.validate(shifts, rules)]


def test_validate_defaults_are_fine() -> None:
    assert win.validate(SHIFTS, RULES) == []


def test_validate_refuses_bad_days() -> None:
    m = lambda s, e: win.ShiftDef("morning", "", "", s, e, 1)  # noqa: E731
    a = lambda s, e: win.ShiftDef("afternoon", "", "", s, e, 2)  # noqa: E731
    assert "The shift must end after it starts" in _problems([m(time(12), time(7))])
    assert "Shifts must not overlap" in _problems([m(time(7), time(13, 30)), a(time(13), time(15))])
    assert "The check-in window starts before midnight" in _problems([m(time(0, 10), time(5))])
    assert "The check-out window ends after midnight" in _problems([m(time(20), time(23, 30))])
    assert "Check-in must close by the end of the shift" in _problems([m(time(7), time(7, 30))])
    # Afternoon check-in (from 12:00) before the morning's closes (12:15).
    assert "Two check-in windows overlap" in _problems(
        [m(time(11, 30), time(12, 15)), a(time(12, 30), time(15))]
    )
    # Morning check-out until 12:59, afternoon ends 12:50... can't (shifts overlap); with a
    # long check-out window instead:
    rules = win.Rules(30, 45, 120, 100)
    assert "Two check-out windows overlap" in _problems(
        [m(time(7), time(12)), a(time(13), time(13, 50))], rules
    )
