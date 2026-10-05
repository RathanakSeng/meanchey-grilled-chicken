"""Migration 0014: inventory_materials, grams columns, material movement sources; downgrade and
back (material rows, balances and movements are removed on the way down)."""

import asyncio

import pytest
from alembic import command
from sqlalchemy.exc import IntegrityError

from tests.test_migration_step_dates import _alembic, _run


def _g_columns() -> list[tuple[str, str]]:
    return asyncio.run(
        _run(
            "SELECT table_name, column_name FROM information_schema.columns "
            "WHERE column_name IN ('g', 'g_delta', 'balance_g_after') "
            "AND table_name LIKE 'inventory_%' ORDER BY table_name, column_name"
        )
    )


def _materials_table() -> list[tuple[str]]:
    return asyncio.run(
        _run("SELECT tablename FROM pg_tables WHERE tablename = 'inventory_materials'")
    )


def test_materials_migration_round_trip() -> None:
    assert _materials_table() == [("inventory_materials",)]
    assert len(_g_columns()) == 3
    _alembic(command.downgrade, "0013")
    try:
        assert _materials_table() == []
        assert _g_columns() == []
        # The old CHECK is back: no material sources.
        with pytest.raises(IntegrityError):
            asyncio.run(
                _run(
                    "INSERT INTO inventory_movements (item_code, count_delta, source) "
                    "VALUES ('chicken', 1, 'material_add')"
                )
            )
    finally:
        _alembic(command.upgrade, "head")
    assert _materials_table() == [("inventory_materials",)]
    assert _g_columns() == [
        ("inventory_balances", "g"),
        ("inventory_movements", "balance_g_after"),
        ("inventory_movements", "g_delta"),
    ]
    # Grams can't go negative; a unit outside count / kg / g is refused.
    with pytest.raises(IntegrityError):
        asyncio.run(
            _run("INSERT INTO inventory_balances (item_code, g) VALUES ('material_neg', -1)")
        )
    with pytest.raises(IntegrityError):
        asyncio.run(
            _run(
                "INSERT INTO inventory_materials (id, item_code, name_km, name_en, unit) VALUES "
                "('00000000-0000-0000-0000-0000000000e1', 'material_mig', 'x', 'x', 'litre')"
            )
        )
