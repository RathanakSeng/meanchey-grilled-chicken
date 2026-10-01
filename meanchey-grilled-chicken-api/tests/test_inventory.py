"""Inventory: movements from production (finish / reopen / cancel), the no-negative rule,
untracked batches, adjustments, access, history and concurrency."""

import asyncio
from decimal import Decimal

import pytest
from sqlalchemy import delete, func, select, update

from app.bootstrap import bootstrap
from app.models import (
    AuditLog,
    InventoryMovement,
    Permission,
    ProductionBatch,
    Role,
    UserPermission,
)
from app.permissions import registry
from tests.conftest import assert_error, auth
from tests.test_production import PRODUCED, Api, ok, standardize_body

BYPRODUCTS = ["gizzard", "liver", "heart", "head"]


@pytest.fixture
async def gm(make_user):
    return await make_user(Role.GENERAL_MANAGER)


@pytest.fixture
def api(client, gm) -> Api:
    return Api(client, gm)


@pytest.fixture
async def supplier(client, gm) -> dict:
    return ok(await client.post("/suppliers", json={"name": "Sokha Farm"}, headers=auth(gm)), 201)


async def stock(client, user) -> dict[str, dict]:
    body = ok(await client.get("/inventory", headers=auth(user)))
    return {i["code"]: i for s in body["sections"] for i in s["items"]}


def amounts(items: dict[str, dict], code: str) -> tuple[int | None, str | None]:
    return items[code]["count"], items[code]["kg"]


async def history(client, user, **params) -> list[dict]:
    r = await client.get("/inventory/movements", params=params, headers=auth(user))
    return ok(r)["items"]


def set_value(client, user, code: str, **body):
    return client.post(f"/inventory/items/{code}/set", json=body, headers=auth(user))


async def step2_for(api: Api, supplier: dict, quantity: int, big: int, small: int) -> dict:
    """Steps 1 and 2 finished for `quantity` chickens, with a confirmed big / small plan."""
    batch = await api.step2(supplier, quantity, plan=False)
    return await api.confirm_plan(batch, big, small)


async def finish3(api: Api, batch: dict, **standardize) -> dict:
    batch = ok(await api.patch(batch, "standardize", **standardize_body(**standardize)))
    return ok(await api.finish(batch, "standardize"))


async def movement_count(session) -> int:
    return await session.scalar(select(func.count()).select_from(InventoryMovement))


# --- Catalog and empty state ---------------------------------------------------------------------


async def test_starts_at_zero_with_every_item(client, gm) -> None:
    r = ok(await client.get("/inventory", headers=auth(gm)))
    assert [s["section"] for s in r["sections"]] == ["stock", "wasted"]
    items = {i["code"]: i for s in r["sections"] for i in s["items"]}
    assert amounts(items, "chicken") == (0, "0.000")
    assert amounts(items, "packs_big") == (0, None)  # count only
    assert amounts(items, "byproduct_processed.liver") == (None, "0.000")  # kg only
    assert items["byproduct_packed.liver"]["name_en"] == "Liver (packed)"
    assert items["byproduct_processed.liver"]["name_km"] == "ថ្លើមមាន់ (ផលិត)"
    assert items["wasted.wings"]["kg_estimated"] is True
    assert {i["group"] for i in items.values()} == {"raw", "processed", "packed", "wasted"}
    assert all(i["updated_at"] is None for i in items.values())
    assert ok(await client.get("/inventory/movements", headers=auth(gm)))["total"] == 0


# --- Production movements ------------------------------------------------------------------------


async def test_done_when_scenario(client, api, supplier, gm) -> None:
    """100 + 50 chickens; steps 2 and 3 of the 50-chicken batch move only its own stock."""
    await api.step1(supplier, 100)
    small = await api.step1(supplier, 50)
    items = await stock(client, gm)
    assert amounts(items, "chicken") == (150, "51.000")  # 2 × 25.500 kg

    small = ok(await api.patch(small, "produced", **PRODUCED))
    small = ok(await api.finish(small, "produced"))
    items = await stock(client, gm)
    assert amounts(items, "chicken") == (100, "25.500")
    assert amounts(items, "wings") == (100, "4.200")
    assert amounts(items, "thighs") == (100, "6.800")
    for code in BYPRODUCTS:
        assert amounts(items, f"byproduct_processed.{code}") == (None, "0.500")

    # 2 × 40 + 19 + 1 = 100 pieces each.
    small = await api.confirm_plan(small, 40, 19)
    await finish3(api, small, big=40, small=19)
    items = await stock(client, gm)
    assert amounts(items, "chicken") == (100, "25.500")
    assert amounts(items, "wings") == (0, "0.000")
    assert amounts(items, "thighs") == (0, "0.000")
    assert amounts(items, "packs_big") == (40, None)
    assert amounts(items, "packs_small") == (19, None)
    # Estimated: 1 × 4.200 / 100 and 1 × 6.800 / 100.
    assert amounts(items, "wasted.wings") == (1, "0.042")
    assert amounts(items, "wasted.thighs") == (1, "0.068")
    for code in BYPRODUCTS:
        assert amounts(items, f"byproduct_processed.{code}") == (None, "0.000")
        assert amounts(items, f"byproduct_packed.{code}") == (None, "0.400")
        assert amounts(items, f"wasted.byproduct.{code}") == (None, "0.100")
    assert items["chicken"]["updated_at"] is not None


async def test_each_finish_writes_exactly_its_movements(client, api, supplier, gm) -> None:
    batch = await api.completed(supplier)  # 10 chickens, 7 + 5 packs, 1 + 1 rejected
    rows = await history(client, gm, batch_id=batch["id"])
    by_step: dict[int, dict[str, dict]] = {}
    for m in rows:
        assert m["source"] == "production" and m["reversal_of"] is None
        assert m["batch"] == {"id": batch["id"], "code": batch["code"]}
        by_step.setdefault(m["step"], {})[m["item_code"]] = m

    def delta(step: int, code: str) -> tuple[int | None, str | None]:
        return by_step[step][code]["count_delta"], by_step[step][code]["kg_delta"]

    assert set(by_step[1]) == {"chicken"}
    assert delta(1, "chicken") == (10, "25.500")

    assert set(by_step[2]) == {"chicken", "wings", "thighs"} | {
        f"byproduct_processed.{c}" for c in BYPRODUCTS
    }
    assert delta(2, "chicken") == (-10, "-25.500")
    assert delta(2, "wings") == (20, "4.200")
    assert delta(2, "thighs") == (20, "6.800")
    assert delta(2, "byproduct_processed.liver") == (None, "0.500")

    assert delta(3, "wings") == (-20, "-4.200")
    assert delta(3, "thighs") == (-20, "-6.800")
    assert delta(3, "packs_big") == (7, None)
    assert delta(3, "packs_small") == (5, None)
    assert delta(3, "wasted.wings") == (1, "0.210")  # 1 × 4.200 / 20
    assert delta(3, "wasted.thighs") == (1, "0.340")  # 1 × 6.800 / 20
    assert by_step[3]["wasted.wings"]["kg_estimated"] is True
    assert by_step[3]["packs_big"]["kg_estimated"] is False
    # By-products: processed loses carry + rejected; packed and wasted get them.
    assert delta(3, "byproduct_processed.liver") == (None, "-0.500")
    assert delta(3, "byproduct_packed.liver") == (None, "0.400")
    assert delta(3, "wasted.byproduct.liver") == (None, "0.100")
    # Balances after are recorded on each movement.
    assert by_step[3]["packs_big"]["balance_count_after"] == 7
    assert by_step[1]["chicken"]["created_by"]["id"] == str(gm.id)


async def test_unassigned_byproduct_stays_processed(client, api, supplier, gm) -> None:
    batch = await api.step2(supplier)
    body = standardize_body()
    body["byproducts"]["liver"] = {"carry_kg": "0.2", "rejected_kg": "0.1"}  # 0.5 produced
    batch = ok(await api.patch(batch, "standardize", **body))
    ok(await api.finish(batch, "standardize"))
    items = await stock(client, gm)
    assert amounts(items, "byproduct_processed.liver") == (None, "0.200")
    assert amounts(items, "byproduct_packed.liver") == (None, "0.200")


async def test_batch_detail_lists_its_stock_changes(api, supplier) -> None:
    batch = await api.step2(supplier)
    assert batch["inventory_tracked"] is True
    changes = [(c["step"], c["item_code"], c["count_delta"]) for c in batch["stock_changes"]]
    assert changes[0] == (1, "chicken", 10)
    assert (2, "chicken", -10) in changes and (2, "wings", 20) in changes
    batch = ok(await api.reopen(batch, "produced"))
    assert [c["step"] for c in batch["stock_changes"]] == [1]  # step 2 was reversed
    assert batch["stock_changes"][0]["name_km"] == "មាន់"


# --- Reopen and cancel ---------------------------------------------------------------------------


async def test_reopen_step_1_reverses_every_step_latest_first(client, api, supplier, gm) -> None:
    batch = await api.completed(supplier)
    originals = await history(client, gm, batch_id=batch["id"])
    batch = ok(await api.reopen(batch, "raw-material"))

    items = await stock(client, gm)
    assert all((i["count"] or 0) == 0 and Decimal(i["kg"] or 0) == 0 for i in items.values()), items
    rows = await history(client, gm, batch_id=batch["id"])
    reversals = [m for m in rows if m["reversal_of"] is not None]
    assert len(reversals) == len(originals)
    assert {m["reason"] for m in reversals} == {"reopen"}
    # Written step 3 first, then 2, then 1 (history is newest first).
    assert [m["step"] for m in reversed(reversals)] == sorted(
        (m["step"] for m in reversals), reverse=True
    )
    by_id = {m["id"]: m for m in originals}
    for r in reversals:
        o = by_id[r["reversal_of"]]
        assert r["item_code"] == o["item_code"]
        assert r["count_delta"] == (-o["count_delta"] if o["count_delta"] is not None else None)
        assert r["kg_estimated"] == o["kg_estimated"]

    # Finishing again writes fresh movements; reopening again reverses only those.
    batch = ok(await api.finish(batch, "raw-material"))
    assert amounts(await stock(client, gm), "chicken") == (10, "25.500")
    batch = ok(await api.reopen(batch, "raw-material"))
    assert amounts(await stock(client, gm), "chicken") == (0, "0.000")
    rows = await history(client, gm, batch_id=batch["id"])
    reversed_ids = [m["reversal_of"] for m in rows if m["reversal_of"] is not None]
    assert len(reversed_ids) == len(set(reversed_ids))  # never reversed twice


async def test_reopen_step_3_reverses_only_step_3(client, api, supplier, gm) -> None:
    batch = await api.completed(supplier)
    batch = ok(await api.reopen(batch, "standardize"))
    items = await stock(client, gm)
    assert amounts(items, "packs_big") == (0, None)
    assert amounts(items, "wasted.wings") == (0, "0.000")
    assert amounts(items, "wings") == (20, "4.200")
    assert amounts(items, "chicken") == (0, "0.000")  # step 2 still finished
    # Finish again: the same movements once more.
    batch = ok(await api.finish(batch, "standardize"))
    assert amounts(await stock(client, gm), "packs_big") == (7, None)


async def test_cancel_reverses_everything(client, api, supplier, gm) -> None:
    batch = await api.step2(supplier)
    other = await api.step1(supplier, 30)
    ok(await api.cancel(batch))
    items = await stock(client, gm)
    assert amounts(items, "chicken") == (30, "25.500")  # only the other batch
    assert amounts(items, "wings") == (0, "0.000")
    assert amounts(items, "byproduct_processed.liver") == (None, "0.000")
    rows = await history(client, gm, batch_id=batch["id"])
    assert {m["reason"] for m in rows if m["reversal_of"]} == {"cancel"}
    assert (await api.get(other))["status"] == "in_progress"


async def test_drafts_write_no_movements(api, supplier, session) -> None:
    batch = await api.create(supplier_id=supplier["id"], weight_kg="10", quantity=4)
    ok(await api.patch(batch, "raw-material", quantity=5))
    assert await movement_count(session) == 0


# --- No negative balances ------------------------------------------------------------------------


async def test_negative_guard_refuses_finish_reopen_and_cancel(
    client, api, supplier, superadmin, session
) -> None:
    batch = await api.step1(supplier, 10)
    # Someone counted only 5 chickens.
    ok(await set_value(client, superadmin, "chicken", count=5, reason="Recount"))
    before = await movement_count(session)

    batch = ok(await api.patch(batch, "produced", **PRODUCED))
    r = await api.finish(batch, "produced")
    assert_error(r, 409, "INVENTORY_INSUFFICIENT")
    assert r.json()["error"]["details"]["items"] == [
        {
            "item_code": "chicken",
            "name_en": "Chicken",
            "name_km": "មាន់",
            "available_count": 5,
            "available_kg": "25.500",
            "needed_count": 10,
            "needed_kg": "25.500",  # both units are reported; only the count is short
        }
    ]
    assert_error(await api.reopen(batch, "raw-material"), 409, "INVENTORY_INSUFFICIENT")
    assert_error(await api.cancel(batch), 409, "INVENTORY_INSUFFICIENT")

    # Nothing changed: no movements, same balance, batch still at step 2 (draft).
    assert await movement_count(session) == before
    assert amounts(await stock(client, superadmin), "chicken") == (5, "25.500")
    current = await api.get(batch)
    assert current["produced"]["status"] == "draft" and current["status"] == "in_progress"
    assert current["raw_material"]["status"] == "finished"

    # Back to 10: everything works again.
    ok(await set_value(client, superadmin, "chicken", count=10, reason="Found them"))
    ok(await api.finish(current, "produced"))


# --- Untracked (older) batches -------------------------------------------------------------------


async def test_untracked_batches_never_move_stock(client, api, supplier, gm, session) -> None:
    batch = await api.create(supplier_id=supplier["id"], weight_kg="25.500", quantity=10)
    await session.execute(
        update(ProductionBatch)
        .where(ProductionBatch.code == batch["code"])
        .values(inventory_tracked=False)
    )
    await session.commit()
    batch = ok(await api.finish(await api.get(batch), "raw-material"))
    batch = ok(await api.patch(batch, "produced", **PRODUCED))
    batch = ok(await api.finish(batch, "produced"))
    batch = ok(await api.reopen(batch, "raw-material"))
    batch = ok(await api.cancel(batch))
    assert await movement_count(session) == 0
    assert batch["inventory_tracked"] is False and batch["stock_changes"] == []


# --- Adjustments ---------------------------------------------------------------------------------


async def test_superadmin_sets_values_with_audit(client, superadmin, gm, session) -> None:
    r = await set_value(client, superadmin, "chicken", count=120, kg="300.25", reason=" Opening ")
    item = ok(r)
    assert (item["count"], item["kg"]) == (120, "300.250")
    ok(await set_value(client, superadmin, "chicken", count=100, reason="Recount"))
    ok(await set_value(client, superadmin, "packs_big", count=8, reason="Opening"))
    ok(await set_value(client, superadmin, "byproduct_packed.liver", kg="1.5", reason="Opening"))

    items = await stock(client, gm)
    assert amounts(items, "chicken") == (100, "300.250")
    rows = await history(client, gm, source="adjustment", item_code="chicken")
    assert [(m["count_delta"], m["kg_delta"]) for m in rows] == [(-20, None), (120, "300.250")]
    assert rows[1]["reason"] == "Opening" and rows[1]["batch"] is None

    logs = list(
        await session.scalars(
            select(AuditLog).where(AuditLog.action == "inventory.adjust").order_by(AuditLog.id)
        )
    )
    assert logs[0].details == {
        "item_code": "chicken",
        "name_en": "Chicken",
        "name_km": "មាន់",
        "from": {"count": 0, "kg": "0.000"},
        "to": {"count": 120, "kg": "300.250"},
        "reason": "Opening",
    }
    # The same value again: no movement, no audit entry.
    ok(await set_value(client, superadmin, "packs_big", count=8, reason="Same"))
    assert len(await history(client, gm, item_code="packs_big")) == 1


@pytest.mark.parametrize(
    ("code", "body", "status", "error"),
    [
        ("chicken", {"count": 1}, 422, "VALIDATION_ERROR"),  # reason missing
        ("chicken", {"count": 1, "reason": "  "}, 422, "VALIDATION_ERROR"),
        ("chicken", {"count": 1, "reason": "x" * 501}, 422, "VALIDATION_ERROR"),
        ("chicken", {"reason": "Nothing"}, 422, "VALIDATION_ERROR"),
        ("chicken", {"count": -1, "reason": "x"}, 422, "VALIDATION_ERROR"),
        ("chicken", {"kg": "-0.5", "reason": "x"}, 422, "VALIDATION_ERROR"),
        ("packs_big", {"kg": "1", "reason": "x"}, 422, "VALIDATION_ERROR"),  # count only
        ("byproduct_packed.liver", {"count": 1, "reason": "x"}, 422, "VALIDATION_ERROR"),
        ("nope", {"count": 1, "reason": "x"}, 404, "INVENTORY_ITEM_NOT_FOUND"),
    ],
)
async def test_set_value_validation(client, superadmin, code, body, status, error) -> None:
    assert_error(await set_value(client, superadmin, code, **body), status, error)


async def test_adjusting_needs_inventory_adjust(client, superadmin, make_user) -> None:
    gm = await make_user(Role.GENERAL_MANAGER)
    sup = await make_user(Role.SUPERVISOR)
    for user in (gm, sup):
        assert_error(
            await set_value(client, user, "chicken", count=1, reason="x"), 403, "MISSING_PERMISSION"
        )
    # The superadmin allows it for the GM (Access tab: Set stock values).
    r = await client.put(
        f"/users/{gm.id}/features/inventory_adjust",
        json={"level": "full"},
        headers=auth(superadmin),
    )
    assert ok(r)["current_level"] == "full"
    ok(await set_value(client, gm, "chicken", count=3, reason="Counted"))


async def test_superadmin_adjustments_read_as_system(client, superadmin, gm) -> None:
    ok(await set_value(client, superadmin, "chicken", count=3, reason="Opening"))
    row = (await history(client, gm))[0]
    assert row["created_by"]["is_system"] is True and row["created_by"]["id"] is None
    assert "superadmin" not in str(row).lower()


# --- History filters -----------------------------------------------------------------------------


async def test_history_filters(client, api, supplier, gm, superadmin) -> None:
    batch = await api.step2(supplier)
    ok(await set_value(client, superadmin, "packs_small", count=2, reason="Opening"))
    assert {m["source"] for m in await history(client, gm, source="production")} == {"production"}
    wasted = await history(client, gm, section="wasted")
    assert wasted == []
    assert {m["item_code"] for m in await history(client, gm, section="stock")} >= {"chicken"}
    part = batch["code"][-6:]
    assert {m["batch"]["code"] for m in await history(client, gm, batch_code=part)} == {
        batch["code"]
    }
    assert await history(client, gm, batch_code="NOPE") == []
    assert len(await history(client, gm, date_from="2000-01-01", date_to="2000-01-02")) == 0
    page = ok(await client.get("/inventory/movements?page_size=2", headers=auth(gm)))
    assert page["page_size"] == 2 and len(page["items"]) == 2 and page["total"] > 2


# --- Concurrency ---------------------------------------------------------------------------------


async def test_concurrent_finishes_keep_correct_totals(client, api, supplier, gm) -> None:
    batches = [
        await api.create(supplier_id=supplier["id"], weight_kg="10.000", quantity=q)
        for q in (11, 12, 13, 14)
    ]
    results = await asyncio.gather(*(api.finish(b, "raw-material") for b in batches))
    assert [r.status_code for r in results] == [200] * 4
    assert amounts(await stock(client, gm), "chicken") == (50, "40.000")
    # The row locks serialize them: every movement saw the previous one's balance.
    rows = await history(client, gm, item_code="chicken")
    afters = sorted(m["balance_count_after"] for m in rows)
    assert len(set(afters)) == 4 and afters[-1] == 50


# --- Access --------------------------------------------------------------------------------------


def test_registry() -> None:
    registry.validate_features()
    inv = registry.FEATURES_BY_CODE["inventory"]
    adjust = registry.FEATURES_BY_CODE["inventory_adjust"]
    assert inv.menu == adjust.menu == "workstation"
    assert inv.level_map == {"off": frozenset(), "view": {"inventory.view"}}
    assert adjust.applies_to == (Role.GENERAL_MANAGER,)
    assert adjust.level_map == {"off": frozenset(), "full": {"inventory.adjust"}}
    d = registry.DEFAULT_PERMISSIONS
    assert "inventory.view" in d[Role.GENERAL_MANAGER]
    assert "inventory.adjust" not in d[Role.GENERAL_MANAGER]
    assert d[Role.SUPERVISOR] & {"inventory.view", "inventory.adjust"} == {"inventory.view"}
    assert not d[Role.STAFF]


async def test_access_levels(client, superadmin, make_user) -> None:
    gm = await make_user(Role.GENERAL_MANAGER)
    sup = await make_user(Role.SUPERVISOR)
    staff = await make_user(Role.STAFF)
    assert_error(await client.get("/inventory", headers=auth(staff)), 403, "MISSING_PERMISSION")
    ok(await client.get("/inventory", headers=auth(sup)))

    features = {
        f["code"]: f
        for m in ok(await client.get(f"/users/{gm.id}/features", headers=auth(superadmin)))["menus"]
        for f in m["features"]
    }
    assert features["inventory"]["current_level"] == "view"
    assert features["inventory_adjust"]["current_level"] == "off"

    # A supervisor (Staff access) gives staff Inventory View, within its own access.
    r = await client.put(
        f"/users/{staff.id}/features/inventory", json={"level": "view"}, headers=auth(sup)
    )
    assert ok(r)["current_level"] == "view"
    ok(await client.get("/inventory/movements", headers=auth(staff)))
    staff_features = {
        f["code"]
        for m in ok(await client.get(f"/users/{staff.id}/features", headers=auth(sup)))["menus"]
        for f in m["features"]
    }
    assert "inventory_adjust" not in staff_features

    # Without Inventory itself, the supervisor can still switch it off, but not give it.
    await client.put(f"/users/{sup.id}/features/inventory", json={"level": "off"}, headers=auth(gm))
    r = await client.put(
        f"/users/{staff.id}/features/inventory", json={"level": "off"}, headers=auth(sup)
    )
    assert ok(r)["current_level"] == "off"
    assert_error(
        await client.put(
            f"/users/{staff.id}/features/inventory", json={"level": "view"}, headers=auth(sup)
        ),
        403,
        "PERMISSION_NOT_HELD",
    )


async def test_backfill_gives_view_to_existing_managers_only(session, make_user) -> None:
    gm = await make_user(Role.GENERAL_MANAGER)
    sup = await make_user(Role.SUPERVISOR)
    staff = await make_user(Role.STAFF)
    codes = ["inventory.view", "inventory.adjust"]
    await session.execute(delete(UserPermission).where(UserPermission.permission_code.in_(codes)))
    await session.execute(delete(Permission).where(Permission.code.in_(codes)))
    await session.commit()

    await bootstrap(session)

    async def held(user) -> set[str]:
        return set(
            await session.scalars(
                select(UserPermission.permission_code).where(
                    UserPermission.user_id == user.id, UserPermission.permission_code.in_(codes)
                )
            )
        )

    assert await held(gm) == {"inventory.view"}
    assert await held(sup) == {"inventory.view"}
    assert await held(staff) == set()
