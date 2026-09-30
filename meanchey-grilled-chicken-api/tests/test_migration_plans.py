"""Migration 0007: in-progress batches with step 2 finished get a pending plan; completed and
cancelled ones get none (legacy); the CHECK keeps a confirmed plan complete."""

import asyncio
import uuid

import pytest
from alembic import command
from sqlalchemy.exc import IntegrityError

from tests.test_migration_step_dates import _alembic, _run


def test_plans_backfill() -> None:
    ids = {name: uuid.uuid4() for name in ("waiting", "early", "completed", "cancelled")}
    _alembic(command.downgrade, "0006")
    try:
        asyncio.run(
            _run(
                "INSERT INTO production_batches (id, code, status, current_step) VALUES "
                "(:waiting, 'PR-20260901-001', 'in_progress', 3), "
                "(:early, 'PR-20260901-002', 'in_progress', 2), "
                "(:completed, 'PR-20260901-003', 'completed', 3), "
                "(:cancelled, 'PR-20260901-004', 'cancelled', 3)",
                "INSERT INTO production_raw_materials"
                " (batch_id, material_kind, status, finished_at, import_date) VALUES"
                " (:waiting, 'chicken', 'finished', now(), '2026-09-01'),"
                " (:early, 'chicken', 'finished', now(), '2026-09-01'),"
                " (:completed, 'chicken', 'finished', now(), '2026-09-01'),"
                " (:cancelled, 'chicken', 'finished', now(), '2026-09-01')",
                "INSERT INTO production_outputs (batch_id, status, finished_at, production_date)"
                " VALUES (:waiting, 'finished', now(), '2026-09-01'),"
                " (:early, 'draft', NULL, NULL),"
                " (:completed, 'finished', now(), '2026-09-01'),"
                " (:cancelled, 'finished', now(), '2026-09-01')",
                **ids,
            )
        )
    finally:
        _alembic(command.upgrade, "head")

    rows = asyncio.run(_run("SELECT batch_id, status, expected_big FROM production_plans"))
    assert rows == [(ids["waiting"], "pending", None)]

    with pytest.raises(IntegrityError):
        asyncio.run(
            _run(
                "UPDATE production_plans SET status = 'confirmed' WHERE batch_id = :b",
                b=ids["waiting"],
            )
        )
    asyncio.run(_run("DELETE FROM production_batches"))
