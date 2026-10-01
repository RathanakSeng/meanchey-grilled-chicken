"""Migration 0010: inventory tables; every existing batch untracked, new batches tracked."""

import asyncio
import uuid

from alembic import command

from tests.test_migration_step_dates import _alembic, _run


def test_inventory_migration() -> None:
    old = uuid.uuid4()
    _alembic(command.downgrade, "0009")
    try:
        asyncio.run(
            _run(
                f"INSERT INTO production_batches (id, code) VALUES ('{old}', 'PR-MIG-INV-001')",
                "INSERT INTO production_raw_materials (batch_id, material_kind) "
                f"VALUES ('{old}', 'chicken')",
            )
        )
    finally:
        _alembic(command.upgrade, "head")

    new = uuid.uuid4()
    try:
        asyncio.run(
            _run(f"INSERT INTO production_batches (id, code) VALUES ('{new}', 'PR-MIG-INV-002')")
        )
        rows = asyncio.run(
            _run(
                "SELECT code, inventory_tracked FROM production_batches "
                "WHERE code LIKE 'PR-MIG-INV-%' ORDER BY code"
            )
        )
        assert rows == [("PR-MIG-INV-001", False), ("PR-MIG-INV-002", True)]
        tables = asyncio.run(
            _run(
                "SELECT tablename FROM pg_tables WHERE tablename LIKE 'inventory_%' "
                "ORDER BY tablename"
            )
        )
        assert tables == [("inventory_balances",), ("inventory_movements",)]
    finally:
        asyncio.run(_run("DELETE FROM production_batches WHERE code LIKE 'PR-MIG-INV-%'"))
