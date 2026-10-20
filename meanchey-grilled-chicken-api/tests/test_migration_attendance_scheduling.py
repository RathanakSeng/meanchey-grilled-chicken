"""Migration 0020: each workplace's shifts and rules become one schedule version (from its
creation date, every weekday), the old table and columns go; `attendance.shifts_manage` holders
get `attendance.scheduling` (audited as a default change); the downgrade puts the latest
version back."""

import asyncio

import pytest
from alembic import command
from sqlalchemy.exc import IntegrityError

from tests.test_migration_step_dates import _alembic, _run


def _columns(table: str) -> set[str]:
    rows = asyncio.run(
        _run(
            "SELECT column_name FROM information_schema.columns WHERE table_name = :t",
            t=table,
        )
    )
    return {r[0] for r in rows}


def test_schedule_versions_and_permission() -> None:
    _alembic(command.downgrade, "0019")
    try:
        assert "open_before_min" in _columns("attendance_workplaces")
        assert not _columns("attendance_schedule_versions")
        asyncio.run(
            _run(
                # A second workplace with its own schedule, created on 2026-10-05 (Phnom Penh).
                "INSERT INTO attendance_workplaces (id, name, open_before_min, absent_after_min, "
                "checkout_window_min, max_accuracy_m, reminders_enabled, count_overtime, "
                "created_at) VALUES (gen_random_uuid(), 'Branch', 15, 20, 30, 50, false, false, "
                "TIMESTAMPTZ '2026-10-04 18:00+00')",
                "INSERT INTO attendance_shifts (id, workplace_id, code, name_km, name_en, "
                "start_time, end_time, position) SELECT gen_random_uuid(), w.id, s.code, s.km, "
                "s.en, s.st, s.et, s.pos FROM attendance_workplaces w, (VALUES "
                "('morning', 'ព្រឹក', 'Early', TIME '08:00', TIME '12:00', 1), "
                "('afternoon', 'រសៀល', 'Late', TIME '13:30', TIME '17:00', 2)) "
                "AS s(code, km, en, st, et, pos) WHERE w.name = 'Branch'",
                # A GM holding the retired permission (the startup sync dropped its row).
                "INSERT INTO permissions (code, module, name_en, name_km, description_en, "
                "description_km, assignable_to, is_active) VALUES ('attendance.shifts_manage', "
                "'attendance', 'x', 'x', 'x', 'x', ARRAY['general_manager'], false) "
                "ON CONFLICT (code) DO NOTHING",
                "INSERT INTO users (id, role, full_name, telegram_username, password_hash) "
                "VALUES (gen_random_uuid(), 'general_manager', 'G', 'mig_sched_gm', 'x')",
                "INSERT INTO user_permissions (user_id, permission_code) SELECT id, "
                "'attendance.shifts_manage' FROM users WHERE telegram_username = 'mig_sched_gm'",
            )
        )
    finally:
        _alembic(command.upgrade, "head")
    assert not {"open_before_min", "count_overtime"} & _columns("attendance_workplaces")
    assert not _columns("attendance_shifts")
    ((effective, weekdays, shifts, *rules),) = asyncio.run(
        _run(
            "SELECT v.effective_from::text, v.weekdays, v.shifts, v.open_before_min, "
            "v.absent_after_min, v.checkout_window_min, v.max_accuracy_m, v.reminders_enabled, "
            "v.count_early_checkin, v.count_overtime FROM attendance_schedule_versions v "
            "JOIN attendance_workplaces w ON w.id = v.workplace_id WHERE w.name = 'Branch'"
        )
    )
    assert effective == "2026-10-05" and weekdays == [1, 2, 3, 4, 5, 6, 7]
    assert [(s["code"], s["name_en"], s["start_time"], s["end_time"]) for s in shifts] == [
        ("morning", "Early", "08:00", "12:00"),
        ("afternoon", "Late", "13:30", "17:00"),
    ]
    assert rules == [15, 20, 30, 50, False, True, False]
    perms = asyncio.run(
        _run(
            "SELECT p.permission_code FROM user_permissions p JOIN users u ON u.id = p.user_id "
            "WHERE u.telegram_username = 'mig_sched_gm'"
        )
    )
    assert perms == [("attendance.scheduling",)]
    ((details,),) = asyncio.run(
        _run(
            "SELECT a.details FROM audit_logs a JOIN users u ON u.id = a.target_user_id "
            "WHERE u.telegram_username = 'mig_sched_gm' AND a.action = 'feature.set'"
        )
    )
    assert details["feature"] == "attendance_scheduling" and details["source"] == "default_change"
    # Weekdays are 1-7, at least one.
    for bad in ("ARRAY[]::smallint[]", "ARRAY[0]::smallint[]", "ARRAY[8]::smallint[]"):
        with pytest.raises(IntegrityError):
            asyncio.run(
                _run(
                    "INSERT INTO attendance_schedule_versions (id, workplace_id, effective_from, "
                    "weekdays, shifts, open_before_min, absent_after_min, checkout_window_min, "
                    "max_accuracy_m, reminders_enabled, count_early_checkin, count_overtime) "
                    f"SELECT gen_random_uuid(), id, '2030-01-01', {bad}, '[]', 30, 45, 59, 100, "
                    "true, true, true FROM attendance_workplaces WHERE name = 'Branch'"
                )
            )
    # Holidays: at most 31 days, end on or after start.
    for start, end in (("2026-10-10", "2026-10-09"), ("2026-10-01", "2026-11-01")):
        with pytest.raises(IntegrityError):
            asyncio.run(
                _run(
                    "INSERT INTO attendance_holidays (id, name_km, name_en, start_date, end_date, "
                    f"scope) VALUES (gen_random_uuid(), 'x', 'x', '{start}', '{end}', 'all')"
                )
            )


def test_downgrade_restores_the_latest_version() -> None:
    asyncio.run(
        _run(
            "INSERT INTO attendance_schedule_versions (id, workplace_id, effective_from, "
            "weekdays, shifts, open_before_min, absent_after_min, checkout_window_min, "
            "max_accuracy_m, reminders_enabled, count_early_checkin, count_overtime) "
            "SELECT gen_random_uuid(), workplace_id, '2099-01-01', ARRAY[1, 2]::smallint[], "
            "shifts, 25, 45, 59, 80, true, true, true FROM attendance_schedule_versions"
        )
    )
    _alembic(command.downgrade, "0019")
    try:
        rules = asyncio.run(
            _run("SELECT open_before_min, max_accuracy_m FROM attendance_workplaces")
        )
        assert set(rules) == {(25, 80)}
        shifts = asyncio.run(_run("SELECT count(*) FROM attendance_shifts"))
        assert shifts[0][0] == 2 * len(rules)
    finally:
        _alembic(command.upgrade, "head")
