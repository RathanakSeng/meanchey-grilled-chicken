"""Migration 0022: `attendance_requests` (one per employee and month, split checks) and the four
`attendance.request_*` notification types; the downgrade removes both."""

import asyncio

import pytest
from alembic import command
from sqlalchemy.exc import IntegrityError

from tests.test_migration_step_dates import _alembic, _run

USER = (
    "INSERT INTO users (id, role, position, full_name, telegram_username, password_hash) "
    "VALUES (gen_random_uuid(), 'staff', 'Cook', 'T', 'mig_req', 'x')"
)


def _request(missing: int, cut: int, work: int, month: int = 9) -> str:
    return (
        "INSERT INTO attendance_requests (id, user_id, year, month, status, missing_minutes, "
        "extra_minutes, absent_minutes, late_minutes, balance_minutes, "
        "requested_salary_cut_minutes, requested_unpaid_work_minutes, type) "
        f"SELECT gen_random_uuid(), id, 2026, {month}, 'pending', {missing}, 0, {missing}, 0, "
        f"-{missing}, {cut}, {work}, 'both' FROM users WHERE telegram_username = 'mig_req'"
    )


def _tables() -> set[str]:
    rows = asyncio.run(_run("SELECT table_name FROM information_schema.tables"))
    return {r[0] for r in rows}


def test_requests_table_and_notification_types() -> None:
    _alembic(command.downgrade, "0021")
    try:
        assert "attendance_requests" not in _tables()
    finally:
        _alembic(command.upgrade, "head")
    assert "attendance_requests" in _tables()
    asyncio.run(_run(USER, _request(90, 30, 60)))
    # One per month; the split has to add up to the missing time.
    with pytest.raises(IntegrityError):
        asyncio.run(_run(_request(90, 30, 60)))
    with pytest.raises(IntegrityError):
        asyncio.run(_run(_request(90, 30, 40, month=8)))
    asyncio.run(_run(_request(90, 90, 0, month=8)))
    # The new notification types are accepted ...
    asyncio.run(
        _run(
            "INSERT INTO notifications (id, user_id, type, entity_type, entity_id) "
            "SELECT gen_random_uuid(), id, 'attendance.request_reminder', 'user', id FROM users "
            "WHERE telegram_username = 'mig_req'"
        )
    )
    # ... and the downgrade removes them with the table.
    _alembic(command.downgrade, "0021")
    try:
        assert "attendance_requests" not in _tables()
        rows = asyncio.run(
            _run("SELECT count(*) FROM notifications WHERE type LIKE 'attendance.request_%'")
        )
        assert rows == [(0,)]
    finally:
        _alembic(command.upgrade, "head")
