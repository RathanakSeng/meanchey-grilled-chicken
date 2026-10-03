"""Migration 0012: order tables, order movement sources, order alert types; downgrade and back."""

import asyncio

import pytest
from alembic import command
from sqlalchemy.exc import IntegrityError

from tests.test_migration_step_dates import _alembic, _run

TABLES = [("order_box_items",), ("order_boxes",), ("order_counters",), ("order_return_items",)]


def _order_tables() -> list[tuple[str]]:
    return asyncio.run(
        _run("SELECT tablename FROM pg_tables WHERE tablename LIKE 'order%' ORDER BY tablename")
    )


def test_orders_migration_round_trip() -> None:
    assert {t for (t,) in _order_tables()} == {t for (t,) in TABLES} | {"orders"}
    _alembic(command.downgrade, "0011")
    try:
        assert _order_tables() == []
        # The old CHECKs are back: no order sources or order alerts.
        with pytest.raises(IntegrityError):
            asyncio.run(
                _run(
                    "INSERT INTO inventory_movements (item_code, count_delta, source) "
                    "VALUES ('packs_big', -1, 'order')"
                )
            )
    finally:
        _alembic(command.upgrade, "head")
    assert {t for (t,) in _order_tables()} == {t for (t,) in TABLES} | {"orders"}
    columns = asyncio.run(
        _run(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'inventory_movements' AND column_name = 'order_id'"
        )
    )
    assert columns == [("order_id",)]
    # Lines: a count xor a kg, and positive.
    with pytest.raises(IntegrityError):
        asyncio.run(
            _run(
                "INSERT INTO order_counters (day, last_number) VALUES ('2026-01-01', 1)",
                "INSERT INTO customers (id, name) VALUES "
                "('00000000-0000-0000-0000-0000000000c1', 'Mig')",
                "INSERT INTO orders (id, code, customer_id, delivery_date) VALUES "
                "('00000000-0000-0000-0000-0000000000a1', 'OR-MIG-001', "
                "'00000000-0000-0000-0000-0000000000c1', '2026-01-01')",
                "INSERT INTO order_boxes (id, order_id, color, position) VALUES "
                "('00000000-0000-0000-0000-0000000000b1', "
                "'00000000-0000-0000-0000-0000000000a1', 'white', 1)",
                "INSERT INTO order_box_items (id, box_id, item_code, count, kg) VALUES "
                "('00000000-0000-0000-0000-0000000000d1', "
                "'00000000-0000-0000-0000-0000000000b1', 'packs_big', 1, 1.5)",
            )
        )
