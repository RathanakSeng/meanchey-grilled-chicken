"""Migration 0019: the workplace flags (default true) and the records' early / overtime minutes,
backfilled from the snapshot times and capped by the workplace's windows."""

import asyncio

from alembic import command

from tests.test_migration_step_dates import _alembic, _run


def _columns(table: str) -> set[str]:
    rows = asyncio.run(
        _run(
            "SELECT column_name FROM information_schema.columns WHERE table_name = :t",
            t=table,
        )
    )
    return {r[0] for r in rows}


def test_extra_time_backfill() -> None:
    _alembic(command.downgrade, "0018")
    try:
        assert "early_minutes" not in _columns("attendance_records")
        assert "count_overtime" not in _columns("attendance_workplaces")
        # The default workplace: open 30 min before, check-out window 59 min.
        asyncio.run(
            _run(
                "INSERT INTO users (id, role, position, full_name, telegram_username, "
                "password_hash) VALUES (gen_random_uuid(), 'staff', 'Cook', 'T', 'mig_extra', 'x')",
                "INSERT INTO attendance_records (id, user_id, work_date, shift_code, workplace_id,"
                " scheduled_start, scheduled_end, status, late_minutes, check_in_at,"
                " checkout_status, check_out_at, source) "
                "SELECT gen_random_uuid(), u.id, d.day, d.shift, w.id, d.s, d.e, d.status, d.late,"
                " d.cin, d.cs, d.cout, 'mini_app' FROM users u, attendance_workplaces w, (VALUES"
                # 20 min early (06:40:30 reads 06:40), 25 min overtime (12:25:40).
                " (DATE '2026-10-01', 'morning', TIMESTAMPTZ '2026-10-01 07:00+07',"
                "  TIMESTAMPTZ '2026-10-01 12:00+07', 'present', 0,"
                "  TIMESTAMPTZ '2026-10-01 06:40:30+07', 'checked_out',"
                "  TIMESTAMPTZ '2026-10-01 12:25:40+07'),"
                # Late, forgot check-out: nothing extra.
                " (DATE '2026-10-01', 'afternoon', TIMESTAMPTZ '2026-10-01 13:00+07',"
                "  TIMESTAMPTZ '2026-10-01 15:00+07', 'late', 10,"
                "  TIMESTAMPTZ '2026-10-01 13:10+07', 'forgot_checkout', NULL),"
                # Beyond the windows (a correction): capped at 30 / 59.
                " (DATE '2026-10-02', 'morning', TIMESTAMPTZ '2026-10-02 07:00+07',"
                "  TIMESTAMPTZ '2026-10-02 12:00+07', 'present', 0,"
                "  TIMESTAMPTZ '2026-10-02 05:00+07', 'checked_out',"
                "  TIMESTAMPTZ '2026-10-02 14:00+07'),"
                # Absent.
                " (DATE '2026-10-02', 'afternoon', TIMESTAMPTZ '2026-10-02 13:00+07',"
                "  TIMESTAMPTZ '2026-10-02 15:00+07', 'absent', 0, NULL, NULL, NULL)"
                ") AS d(day, shift, s, e, status, late, cin, cs, cout) "
                "WHERE u.telegram_username = 'mig_extra' AND w.is_default",
            )
        )
    finally:
        _alembic(command.upgrade, "head")
    rows = asyncio.run(
        _run(
            "SELECT work_date::text, shift_code, early_minutes, overtime_minutes, early_counts, "
            "overtime_counts FROM attendance_records ORDER BY work_date, scheduled_start"
        )
    )
    assert rows == [
        ("2026-10-01", "morning", 20, 25, True, True),
        ("2026-10-01", "afternoon", 0, 0, True, True),
        ("2026-10-02", "morning", 30, 59, True, True),
        ("2026-10-02", "afternoon", 0, 0, True, True),
    ]
    # (Since 0020 the flags live on the schedule versions.)
    flags = asyncio.run(
        _run("SELECT count_early_checkin, count_overtime FROM attendance_schedule_versions")
    )
    assert flags == [(True, True)]
