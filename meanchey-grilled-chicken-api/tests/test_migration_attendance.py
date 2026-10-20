"""Migration 0018: attendance tables and seeds (the default workplace with its rules and its
own shifts; since 0020 one schedule version), users.workplace_id backfilled for staff and
supervisors; the downgrade refuses while records exist."""

import asyncio

import pytest
from alembic import command
from sqlalchemy.exc import IntegrityError

from tests.test_migration_step_dates import _alembic, _run


def _tables() -> list[str]:
    rows = asyncio.run(
        _run("SELECT tablename FROM pg_tables WHERE tablename LIKE 'attendance_%' ORDER BY 1")
    )
    return [r[0] for r in rows]


def test_attendance_migration_round_trip() -> None:
    assert _tables() == [
        "attendance_holiday_workplaces",
        "attendance_holidays",
        "attendance_records",
        "attendance_reminders",
        "attendance_requests",
        "attendance_schedule_versions",
        "attendance_untracked_periods",
        "attendance_workplaces",
    ]
    _alembic(command.downgrade, "0017")
    try:
        assert _tables() == []
        # Users created before attendance existed: a GM, a supervisor and staff.
        asyncio.run(
            _run(
                "INSERT INTO users (id, role, position, full_name, telegram_username, "
                "password_hash) VALUES "
                "(gen_random_uuid(), 'general_manager', NULL, 'G', 'mig_gm', 'x'), "
                "(gen_random_uuid(), 'supervisor', NULL, 'S', 'mig_sup', 'x'), "
                "(gen_random_uuid(), 'staff', 'Cook', 'T', 'mig_staff', 'x')"
            )
        )
    finally:
        _alembic(command.upgrade, "head")
    workplaces = asyncio.run(
        _run("SELECT id, name, latitude, radius_m, is_default FROM attendance_workplaces")
    )
    assert len(workplaces) == 1
    default_id, name, lat, radius, is_default = workplaces[0]
    assert (name, lat, radius, is_default) == ("Mean Chey", None, 100, True)
    assigned = dict(
        asyncio.run(
            _run(
                "SELECT telegram_username, workplace_id FROM users "
                "WHERE telegram_username LIKE 'mig_%'"
            )
        )
    )
    assert assigned == {"mig_gm": None, "mig_sup": default_id, "mig_staff": default_id}
    ((workplace_id, shifts, weekdays, *rules),) = asyncio.run(
        _run(
            "SELECT workplace_id, shifts, weekdays, open_before_min, absent_after_min, "
            "checkout_window_min, max_accuracy_m, reminders_enabled "
            "FROM attendance_schedule_versions"
        )
    )
    assert workplace_id == default_id and weekdays == [1, 2, 3, 4, 5, 6, 7]
    assert [(s["code"], s["start_time"], s["end_time"]) for s in shifts] == [
        ("morning", "07:00", "12:00"),
        ("afternoon", "13:00", "15:00"),
    ]
    assert rules == [30, 45, 59, 100, True]
    # One version per workplace and date.
    with pytest.raises(IntegrityError):
        asyncio.run(
            _run(
                "INSERT INTO attendance_schedule_versions (id, workplace_id, effective_from, "
                "weekdays, shifts, open_before_min, absent_after_min, checkout_window_min, "
                "max_accuracy_m, reminders_enabled, count_early_checkin, count_overtime) "
                "SELECT gen_random_uuid(), workplace_id, effective_from, weekdays, shifts, 30, "
                "45, 59, 100, true, true, true FROM attendance_schedule_versions"
            )
        )
    # Names are unique among active workplaces (case-insensitive).
    with pytest.raises(IntegrityError):
        asyncio.run(
            _run(
                "INSERT INTO attendance_workplaces (id, name) "
                "VALUES (gen_random_uuid(), 'mean chey')"
            )
        )
    # Only one default workplace.
    with pytest.raises(IntegrityError):
        asyncio.run(
            _run(
                "INSERT INTO attendance_workplaces (id, name, is_default) "
                "VALUES (gen_random_uuid(), 'Second', true)"
            )
        )
    # An absent record can't have a check-in.
    with pytest.raises(IntegrityError):
        asyncio.run(
            _run(
                "INSERT INTO attendance_records (id, user_id, work_date, shift_code, "
                "scheduled_start, scheduled_end, status, check_in_at, source) "
                "SELECT gen_random_uuid(), id, '2026-10-13', 'morning', now(), now(), 'absent', "
                "now(), 'auto' FROM users WHERE telegram_username = 'mig_staff'"
            )
        )


def test_downgrade_refused_with_records() -> None:
    asyncio.run(
        _run(
            "INSERT INTO users (id, role, position, full_name, telegram_username, password_hash) "
            "VALUES (gen_random_uuid(), 'staff', 'Cook', 'T', 'mig_rec', 'x')",
            "INSERT INTO attendance_records (id, user_id, work_date, shift_code, "
            "scheduled_start, scheduled_end, status, source) "
            "SELECT gen_random_uuid(), id, '2026-10-13', 'morning', now(), now(), 'absent', "
            "'auto' FROM users WHERE telegram_username = 'mig_rec'",
        )
    )
    with pytest.raises(RuntimeError, match="attendance record"):
        _alembic(command.downgrade, "0017")
    assert _tables()  # still there
