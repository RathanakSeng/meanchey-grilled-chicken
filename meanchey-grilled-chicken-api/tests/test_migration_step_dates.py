"""Migration 0006: step dates backfilled from `finished_at` (BUSINESS_TIMEZONE); the batch date
is dropped."""

import asyncio
import uuid

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from tests.conftest import ROOT, TEST_DATABASE_URL


def _alembic(action, revision: str) -> None:
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.attributes["configure_logger"] = False
    cfg.attributes["database_url"] = TEST_DATABASE_URL
    action(cfg, revision)


async def _run(*statements: str, **params) -> list:
    eng = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
    try:
        async with eng.begin() as conn:
            result = None
            for statement in statements:
                result = await conn.execute(text(statement), params)
            return list(result) if result is not None and result.returns_rows else []
    finally:
        await eng.dispose()


def test_step_dates_backfill() -> None:
    finished, draft = uuid.uuid4(), uuid.uuid4()
    _alembic(command.downgrade, "0005")
    try:
        asyncio.run(
            _run(
                "INSERT INTO production_batches (id, code, production_date, current_step) VALUES "
                "(:finished, 'PR-20260930-001', '2026-09-30', 3), "
                "(:draft, 'PR-20260930-002', '2026-09-30', 1)",
                # 17:30 UTC on 30 Sep = 1 Oct in Phnom Penh; 03:00 UTC on 2 Oct = 2 Oct.
                "INSERT INTO production_raw_materials"
                " (batch_id, material_kind, status, finished_at) VALUES"
                " (:finished, 'chicken', 'finished', '2026-09-30 17:30+00'),"
                " (:draft, 'chicken', 'draft', NULL)",
                "INSERT INTO production_outputs (batch_id, status, finished_at)"
                " VALUES (:finished, 'finished', '2026-10-02 03:00+00')",
                "INSERT INTO production_packaging (batch_id, status) VALUES (:finished, 'draft')",
                finished=finished,
                draft=draft,
            )
        )
    finally:
        _alembic(command.upgrade, "head")

    rows = asyncio.run(
        _run(
            "SELECT b.code, r.import_date, o.production_date, p.packaging_date "
            "FROM production_batches b "
            "JOIN production_raw_materials r ON r.batch_id = b.id "
            "LEFT JOIN production_outputs o ON o.batch_id = b.id "
            "LEFT JOIN production_packaging p ON p.batch_id = b.id ORDER BY b.code"
        )
    )
    assert [(code, str(i), str(p), pk) for code, i, p, pk in rows] == [
        ("PR-20260930-001", "2026-10-01", "2026-10-02", None),
        ("PR-20260930-002", "None", "None", None),
    ]
    columns = asyncio.run(
        _run(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'production_batches'"
        )
    )
    assert "production_date" not in {c for (c,) in columns}

    # The CHECKs: a finished step needs its date, a draft can't have one.
    with pytest.raises(IntegrityError):
        asyncio.run(
            _run(
                "UPDATE production_packaging SET status = 'finished' WHERE batch_id = :b",
                b=finished,
            )
        )
    with pytest.raises(IntegrityError):
        asyncio.run(
            _run(
                "UPDATE production_raw_materials SET import_date = '2026-10-01'"
                " WHERE batch_id = :b",
                b=draft,
            )
        )
