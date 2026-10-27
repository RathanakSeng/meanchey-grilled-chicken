"""Migration 0030: clears, their lines and counters, `inventory_movements.clear_id` and the
`clear` source, the `inventory.cleared` notification type; downgrade drops them (refused while
clears exist)."""

import asyncio

import pytest
from alembic import command
from sqlalchemy.exc import IntegrityError

from tests.test_migration_attendance_scheduling import _columns
from tests.test_migration_step_dates import _alembic, _run

C = "inventory_clears"
L = "inventory_clear_lines"
CLEAR_ID = "00000000-0000-0000-0000-00000000c030"


def test_tables_and_checks_round_trip() -> None:
    assert {"code", "reason", "impacts_snapshot", "created_by"} <= set(_columns(C))
    assert {"item_code", "count", "kg", "g", "m2", "moved_to_item_code"} <= set(_columns(L))
    assert "clear_id" in _columns("inventory_movements")
    with pytest.raises(IntegrityError):
        asyncio.run(_run(f"INSERT INTO {C} (id, code, reason) VALUES ('{CLEAR_ID}', 'CL-1', '')"))
    asyncio.run(_run(f"INSERT INTO {C} (id, code, reason) VALUES ('{CLEAR_ID}', 'CL-1', 'x')"))
    try:
        with pytest.raises(IntegrityError):
            asyncio.run(
                _run(
                    f"INSERT INTO {L} (id, clear_id, position, item_code) "
                    f"VALUES (gen_random_uuid(), '{CLEAR_ID}', 1, 'packs_big')"
                )
            )
        # A clear exists: the downgrade refuses.
        with pytest.raises(RuntimeError):
            _alembic(command.downgrade, "0029")
    finally:
        asyncio.run(_run(f"DELETE FROM {C} WHERE id = '{CLEAR_ID}'"))
    _alembic(command.downgrade, "0029")
    try:
        assert _columns(C) == set() and _columns(L) == set()
        assert "clear_id" not in _columns("inventory_movements")
    finally:
        _alembic(command.upgrade, "head")
    assert "impacts_snapshot" in _columns(C)
