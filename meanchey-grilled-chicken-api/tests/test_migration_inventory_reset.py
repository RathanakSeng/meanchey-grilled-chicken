"""Migration 0011: adjustments removed, balances and balances-after recomputed from production."""

import asyncio

from alembic import command

from tests.test_migration_step_dates import _alembic, _run

ITEMS = ("chicken", "packs_big")


def _seed() -> None:
    asyncio.run(
        _run(
            "DELETE FROM inventory_movements",
            "DELETE FROM inventory_balances",
            # Balances as left by production + adjustments.
            "INSERT INTO inventory_balances (item_code, count, kg) VALUES "
            "('chicken', 12, 30.000), ('packs_big', 8, NULL)",
            "INSERT INTO inventory_movements (item_code, count_delta, kg_delta, source, step, "
            "reason, balance_count_after, balance_kg_after, created_at) VALUES "
            "('chicken', 10, 25.500, 'production', 1, NULL, 10, 25.500, '2026-10-01 01:00+00'), "
            "('chicken', 5, 10.000, 'adjustment', NULL, 'Opening', 15, 35.500, "
            "'2026-10-01 02:00+00'), "
            "('chicken', -3, -5.500, 'production', 2, NULL, 12, 30.000, '2026-10-01 03:00+00'), "
            "('packs_big', 8, NULL, 'adjustment', NULL, 'Opening', 8, NULL, "
            "'2026-10-01 04:00+00')",
        )
    )


def _state() -> tuple[list, list]:
    balances = asyncio.run(
        _run("SELECT item_code, count, kg FROM inventory_balances ORDER BY item_code")
    )
    movements = asyncio.run(
        _run(
            "SELECT item_code, source, balance_count_after, balance_kg_after "
            "FROM inventory_movements ORDER BY created_at, id"
        )
    )
    return balances, movements


def test_inventory_reset_migration() -> None:
    _alembic(command.downgrade, "0010")
    try:
        _seed()
    finally:
        _alembic(command.upgrade, "head")

    try:
        balances, movements = _state()
        assert [(c, n, str(k) if k is not None else None) for c, n, k in balances] == [
            ("chicken", 7, "20.000"),
            ("packs_big", 0, None),  # only an adjustment: back to zero, kg stays untracked
        ]
        assert [(c, s, n, str(k)) for c, s, n, k in movements] == [
            ("chicken", "production", 10, "25.500"),
            ("chicken", "production", 7, "20.000"),
        ]

        # Idempotent: a second run changes nothing.
        _alembic(command.downgrade, "0010")
        _alembic(command.upgrade, "head")
        assert _state() == (balances, movements)
    finally:
        asyncio.run(_run("DELETE FROM inventory_movements", "DELETE FROM inventory_balances"))
