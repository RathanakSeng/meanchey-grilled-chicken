"""Migration 0027: the GPS accuracy rule goes (column and CHECK); downgrade puts 100 m back."""

import asyncio

import pytest
from alembic import command
from sqlalchemy.exc import IntegrityError

from tests.test_migration_attendance_scheduling import _columns
from tests.test_migration_step_dates import _alembic, _run

T = "attendance_schedule_versions"


def test_accuracy_rule_dropped_and_restored() -> None:
    assert "max_accuracy_m" not in _columns(T)
    _alembic(command.downgrade, "0026")
    try:
        assert "max_accuracy_m" in _columns(T)
        values = asyncio.run(_run(f"SELECT DISTINCT max_accuracy_m FROM {T}"))
        assert values == [(100,)]
        with pytest.raises(IntegrityError):
            asyncio.run(_run(f"UPDATE {T} SET max_accuracy_m = 5"))
    finally:
        _alembic(command.upgrade, "head")
    assert "max_accuracy_m" not in _columns(T)
