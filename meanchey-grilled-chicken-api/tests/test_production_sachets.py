"""Production step 3: satay sachets used, one per pack (4-piece per big pack, 2-piece per small).

Auto values follow the packs, manual values are kept, one comment covers both the plan and the
sachet differences, Finish takes the sachets from the preparations oldest first, reopen gives
them back, and the plan detail compares what the plan needs with the stock.
"""

import asyncio
import uuid

import pytest
from alembic import command
from sqlalchemy import select, update

from app.models import AuditLog, ProductionBatch, Role
from app.permissions import registry
from tests.conftest import SACHET_TEST_STOCK, assert_error, auth, set_sachet_stock
from tests.test_inventory import history, stock
from tests.test_migration_step_dates import _alembic, _run
from tests.test_preparations import Prep, add_stock, materials
from tests.test_production import PRODUCED, Api, ok, standardize_body


@pytest.fixture
async def gm(make_user):
    # GM defaults plus inventory history (stock changes and movements).
    return await make_user(
        Role.GENERAL_MANAGER,
        perms=sorted(registry.DEFAULT_PERMISSIONS[Role.GENERAL_MANAGER] | {"inventory.history"}),
    )


@pytest.fixture
def api(client, gm) -> Api:
    return Api(client, gm)


@pytest.fixture
async def supplier(client, gm) -> dict:
    return ok(await client.post("/suppliers", json={"name": "Sokha Farm"}, headers=auth(gm)), 201)


def sachets(batch: dict) -> tuple:
    s = batch["standardize"]
    return s["sachets_4_used"], s["sachets_2_used"], s["sachets_4_manual"], s["sachets_2_manual"]


async def drafted(api: Api, supplier: dict, **standardize) -> dict:
    """Steps 1-2 finished, plan 7 + 5 confirmed, step 3 saved (balanced 10-chicken batch)."""
    batch = await api.step2(supplier)
    return ok(await api.patch(batch, "standardize", **standardize_body(**standardize)))


# --- Auto and manual -----------------------------------------------------------------------------


async def test_sachets_follow_the_packs_on_auto(api, supplier) -> None:
    batch = await drafted(api, supplier)
    assert sachets(batch) == (7, 5, False, False)
    assert batch["standardize"]["sachet_stock"] == {"4": SACHET_TEST_STOCK, "2": SACHET_TEST_STOCK}
    # A client value on auto is ignored: the server stores the pack count.
    batch = ok(await api.patch(batch, "standardize", sachets_4_used=99, sachets_2_used=0))
    assert sachets(batch) == (7, 5, False, False)
    batch = ok(await api.patch(batch, "standardize", big_packages=6, small_packages=7))
    assert sachets(batch) == (6, 7, False, False)


async def test_manual_values_are_kept_until_reset_to_auto(api, supplier) -> None:
    batch = await drafted(api, supplier)
    batch = ok(await api.patch(batch, "standardize", sachets_4_manual=True, sachets_4_used=9))
    assert sachets(batch) == (9, 5, True, False)
    # Packs change: the manual size keeps its value, the auto one follows.
    batch = ok(await api.patch(batch, "standardize", big_packages=6, small_packages=7))
    assert sachets(batch) == (9, 7, True, False)
    batch = ok(await api.patch(batch, "standardize", sachets_4_manual=False))
    assert sachets(batch) == (6, 7, False, False)


async def test_cleared_manual_value_defaults_to_the_packs_at_finish(api, supplier) -> None:
    batch = await drafted(api, supplier)
    batch = ok(await api.patch(batch, "standardize", sachets_2_manual=True, sachets_2_used=None))
    assert sachets(batch) == (7, None, False, True)
    batch = ok(await api.finish(batch, "standardize"))
    assert sachets(batch) == (7, 5, False, True)


# --- One comment for both reasons ----------------------------------------------------------------


@pytest.mark.parametrize("used", [8, 6])
async def test_sachets_that_differ_need_a_comment(client, api, supplier, gm, used) -> None:
    batch = await drafted(api, supplier)
    batch = ok(await api.patch(batch, "standardize", sachets_4_manual=True, sachets_4_used=used))
    r = await api.finish(batch, "standardize")
    assert_error(r, 422, "PRODUCTION_SACHET_COMMENT_REQUIRED")
    assert r.json()["error"]["details"] == {
        "4": {"expected": 7, "used": used},
        "2": {"expected": 5, "used": 5},
    }
    batch = ok(await api.patch(batch, "standardize", comment="   "))
    assert_error(await api.finish(batch, "standardize"), 422, "PRODUCTION_SACHET_COMMENT_REQUIRED")
    batch = ok(await api.patch(batch, "standardize", comment="Two sachets torn"))
    batch = ok(await api.finish(batch, "standardize"))
    items = await stock(client, gm)
    assert items["satay_sachet_4"]["count"] == SACHET_TEST_STOCK - used
    assert items["satay_sachet_2"]["count"] == SACHET_TEST_STOCK - 5


async def test_plan_difference_alone_keeps_its_error(api, supplier) -> None:
    # 6 + 7 packs against a 7 + 5 plan; sachets on auto (6 and 7).
    batch = await drafted(api, supplier, big=6, small=7, rejected_wings=1, rejected_thighs=1)
    r = await api.finish(batch, "standardize")
    assert_error(r, 422, "PRODUCTION_PLAN_COMMENT_REQUIRED")
    assert r.json()["error"]["details"] == {
        "planned": {"big": 7, "small": 5},
        "actual": {"big": 6, "small": 7},
    }


async def test_both_reasons_one_comment(api, supplier) -> None:
    batch = await drafted(api, supplier, big=6, small=7, rejected_wings=1, rejected_thighs=1)
    batch = ok(await api.patch(batch, "standardize", sachets_2_manual=True, sachets_2_used=9))
    r = await api.finish(batch, "standardize")
    assert_error(r, 422, "PRODUCTION_PLAN_COMMENT_REQUIRED")
    assert r.json()["error"]["details"] == {
        "planned": {"big": 7, "small": 5},
        "actual": {"big": 6, "small": 7},
        "sachets": {"4": {"expected": 6, "used": 6}, "2": {"expected": 7, "used": 9}},
        "reasons": ["plan", "sachets"],
    }
    batch = ok(await api.patch(batch, "standardize", comment="Short of chicken, sachets split"))
    batch = ok(await api.finish(batch, "standardize"))
    assert batch["status"] == "completed" and sachets(batch) == (6, 9, False, True)


# --- Inventory -----------------------------------------------------------------------------------


async def test_not_enough_sachets_refuses_finish(api, supplier, session) -> None:
    batch = await drafted(api, supplier)
    await set_sachet_stock(session, 3, 100)
    batch = await api.get(batch)
    assert batch["standardize"]["sachet_stock"] == {"4": 3, "2": 100}
    r = await api.finish(batch, "standardize")
    assert_error(r, 409, "INVENTORY_INSUFFICIENT")
    [short] = r.json()["error"]["details"]["items"]
    assert (short["item_code"], short["available_count"], short["needed_count"]) == (
        "satay_sachet_4",
        3,
        7,
    )
    batch = await api.get(batch)
    assert batch["standardize"]["status"] == "draft" and batch["stock_changes"][-1]["step"] == 2


async def test_finish_takes_sachets_oldest_preparation_first_and_reopen_returns_them(
    client, api, supplier, gm, session
) -> None:
    await set_sachet_stock(session, 0, 0)
    ms = await materials(client, gm)
    await add_stock(client, gm, ms["Satay sauce"], "1000")
    await add_stock(client, gm, ms["Zip bag 7 (2-piece packs)"], "1")
    await add_stock(client, gm, ms["Zip bag 7 (4-piece packs)"], "1")
    prep = Prep(client, gm)

    def line(size: int, n: int) -> dict:
        return {"pack_size": size, "satay_g": "100", "zip_bag_qty": "0.1", "sachets": n}

    older = await prep.finished("satay_sachet", [line(4, 4), line(2, 10)])
    newer = await prep.finished("satay_sachet", [line(4, 10), line(2, 10)])

    async def sources(code: str) -> list[tuple[str, int]]:
        detail = ok(await client.get(f"/inventory/items/{code}", headers=auth(gm)))
        total = sum(s["count"] for s in detail["preparation_sources"])
        assert total == detail["count"]  # the breakdown adds up to the balance
        return [(s["code"], s["count"]) for s in detail["preparation_sources"]]

    batch = await drafted(api, supplier)
    batch = ok(await api.finish(batch, "standardize"))
    # 7 × 4-piece: all 4 of the older preparation, then 3 of the newer; 5 × 2-piece: the older.
    assert await sources("satay_sachet_4") == [(newer["code"], 7)]
    assert await sources("satay_sachet_2") == [(older["code"], 5), (newer["code"], 10)]
    moved = [
        (m["item_code"], m["count_delta"], m["preparation"]["code"], m["step"])
        for m in await history(client, gm, batch_id=batch["id"])
        if m["item_code"].startswith("satay_sachet")
    ]
    assert sorted(moved) == sorted(
        [
            ("satay_sachet_4", -4, older["code"], 3),
            ("satay_sachet_4", -3, newer["code"], 3),
            ("satay_sachet_2", -5, older["code"], 3),
        ]
    )
    changes = {
        (c["item_code"], c["count_delta"])
        for c in batch["stock_changes"]
        if c["item_code"].startswith("satay_sachet")
    }
    # One row per item: the preparations' parts summed.
    assert changes == {("satay_sachet_4", -7), ("satay_sachet_2", -5)}

    # A preparation whose sachets production used can't be reopened.
    r = await prep.action(await prep.get(older), "reopen")
    assert_error(r, 409, "INVENTORY_INSUFFICIENT")
    shorts = {
        i["item_code"]: (i["available_count"], i["needed_count"])
        for i in r.json()["error"]["details"]["items"]
    }
    assert shorts == {"satay_sachet_4": (0, 4), "satay_sachet_2": (5, 10)}

    # Reopening step 3 gives every sachet back to the preparation it came from.
    batch = ok(await api.reopen(batch, "standardize"))
    assert await sources("satay_sachet_4") == [(older["code"], 4), (newer["code"], 10)]
    assert await sources("satay_sachet_2") == [(older["code"], 10), (newer["code"], 10)]
    assert not [c for c in batch["stock_changes"] if c["step"] == 3]
    # Now the preparation can be reopened.
    assert ok(await prep.action(await prep.get(older), "reopen"))["status"] == "draft"


async def test_cancel_after_reopen_leaves_the_sachets_in_stock(client, api, supplier, gm) -> None:
    batch = await drafted(api, supplier)
    batch = ok(await api.finish(batch, "standardize"))
    batch = ok(await api.reopen(batch, "standardize"))
    batch = ok(await api.cancel(batch))
    items = await stock(client, gm)
    assert items["satay_sachet_4"]["count"] == SACHET_TEST_STOCK
    assert items["satay_sachet_2"]["count"] == SACHET_TEST_STOCK


async def test_untracked_batches_never_touch_sachets(client, api, supplier, gm, session) -> None:
    batch = await api.create(supplier_id=supplier["id"], weight_kg="25.500", quantity=10)
    await session.execute(
        update(ProductionBatch)
        .where(ProductionBatch.code == batch["code"])
        .values(inventory_tracked=False)
    )
    await session.commit()
    batch = ok(await api.finish(await api.get(batch), "raw-material"))
    batch = ok(await api.patch(batch, "produced", **PRODUCED))
    batch = await api.confirm_plan(ok(await api.finish(batch, "produced")))
    batch = ok(await api.patch(batch, "standardize", **standardize_body()))
    assert batch["standardize"]["sachet_stock"] is None
    batch = ok(await api.finish(batch, "standardize"))
    assert sachets(batch) == (7, 5, False, False)
    items = await stock(client, gm)
    assert items["satay_sachet_4"]["count"] == SACHET_TEST_STOCK
    assert items["satay_sachet_2"]["count"] == SACHET_TEST_STOCK


async def test_audit_records_the_sachets_used(api, supplier, session) -> None:
    batch = await drafted(api, supplier)
    batch = ok(await api.patch(batch, "standardize", sachets_4_manual=True, sachets_4_used=8))
    batch = ok(await api.patch(batch, "standardize", comment="One extra"))
    ok(await api.finish(batch, "standardize"))
    log = await session.scalar(
        select(AuditLog)
        .where(AuditLog.action == "production.step_finish")
        .order_by(AuditLog.id.desc())
    )
    assert log is not None
    assert log.details["sachets_4_used"] == 8 and log.details["sachets_2_used"] == 5


# --- Plan detail ---------------------------------------------------------------------------------


async def test_plan_detail_compares_needed_sachets_with_stock(
    client, api, supplier, gm, session
) -> None:
    batch = await api.step2(supplier)  # plan 7 + 5
    await set_sachet_stock(session, 4, 50)
    url = f"/production-plans/{batch['id']}"
    detail = ok(await client.get(url, headers=auth(gm)))
    assert detail["sachets"] == {
        "needed": {"4": 7, "2": 5},
        "in_stock": {"4": 4, "2": 50},
        "short": {"4": 3, "2": 0},
    }
    await set_sachet_stock(session, 100, 100)
    batch = ok(await api.patch(await api.get(batch), "standardize", **standardize_body()))
    ok(await api.finish(batch, "standardize"))
    assert ok(await client.get(url, headers=auth(gm)))["sachets"] is None


async def test_plan_detail_without_expected_counts(client, api, supplier, gm) -> None:
    batch = await api.step2(supplier, plan=False)
    detail = ok(await client.get(f"/production-plans/{batch['id']}", headers=auth(gm)))
    assert detail["sachets"] is None


# --- Migration 0025 ------------------------------------------------------------------------------


def test_migration_backfills_sachets_from_the_packs() -> None:
    finished, draft = uuid.uuid4(), uuid.uuid4()
    _alembic(command.downgrade, "0024")
    try:
        statements = []
        for batch_id, code in ((finished, "PR-MIG-SAC-001"), (draft, "PR-MIG-SAC-002")):
            statements += [
                f"INSERT INTO production_batches (id, code, inventory_tracked) "
                f"VALUES ('{batch_id}', '{code}', true)",
                "INSERT INTO production_raw_materials (batch_id, material_kind) "
                f"VALUES ('{batch_id}', 'chicken')",
            ]
        statements += [
            "INSERT INTO production_packaging (batch_id, status, packaging_date, big_packages, "
            f"small_packages) VALUES ('{finished}', 'finished', '2026-10-01', 7, 5)",
            f"INSERT INTO production_packaging (batch_id, big_packages) VALUES ('{draft}', 3)",
        ]
        asyncio.run(_run(*statements))
    finally:
        _alembic(command.upgrade, "head")
    try:
        rows = asyncio.run(
            _run(
                "SELECT b.code, p.sachets_4_used, p.sachets_2_used, p.sachets_4_manual, "
                "p.sachets_2_manual FROM production_packaging p "
                "JOIN production_batches b ON b.id = p.batch_id "
                "WHERE b.code LIKE 'PR-MIG-SAC-%' ORDER BY b.code"
            )
        )
        assert rows == [
            ("PR-MIG-SAC-001", 7, 5, False, False),
            ("PR-MIG-SAC-002", 3, None, False, False),
        ]
        moved = asyncio.run(
            _run(
                "SELECT count(*) FROM inventory_movements m JOIN production_batches b "
                "ON b.id = m.batch_id WHERE b.code LIKE 'PR-MIG-SAC-%'"
            )
        )
        assert moved == [(0,)]
    finally:
        asyncio.run(_run("DELETE FROM production_batches WHERE code LIKE 'PR-MIG-SAC-%'"))
