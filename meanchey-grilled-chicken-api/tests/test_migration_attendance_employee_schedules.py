"""Migration 0029: employee override versions and holiday exceptions (their CHECKs), three
notification types; downgrade drops both tables and those notifications."""

import asyncio

import pytest
from alembic import command
from sqlalchemy.exc import IntegrityError

from tests.test_migration_attendance_scheduling import _columns
from tests.test_migration_step_dates import _alembic, _run

O = "attendance_employee_overrides"  # noqa: E741
E = "attendance_holiday_exceptions"


def test_tables_and_checks_round_trip() -> None:
    assert {"weekdays", "shift_codes", "shift_times", "kept_shifts"} <= set(_columns(O))
    assert {"holiday_id", "user_id", "date", "shift_codes", "shift_times"} <= set(_columns(E))
    user = (
        "INSERT INTO users (id, role, position, full_name, telegram_username, password_hash) "
        "VALUES ('00000000-0000-0000-0000-00000000c029', 'staff', 'Cook', 'T', 'mig_c029', 'x')"
    )
    asyncio.run(_run(user))
    try:
        for bad in ("ARRAY[0]::smallint[]", "ARRAY[]::smallint[]"):
            with pytest.raises(IntegrityError):
                asyncio.run(
                    _run(
                        f"INSERT INTO {O} (id, user_id, effective_from, weekdays) VALUES "
                        f"(gen_random_uuid(), '00000000-0000-0000-0000-00000000c029', "
                        f"'2026-11-01', {bad})"
                    )
                )
        _alembic(command.downgrade, "0028")
        try:
            assert _columns(O) == set() and _columns(E) == set()
        finally:
            _alembic(command.upgrade, "head")
        assert "kept_shifts" in _columns(O)
    finally:
        asyncio.run(_run("DELETE FROM users WHERE telegram_username = 'mig_c029'"))
