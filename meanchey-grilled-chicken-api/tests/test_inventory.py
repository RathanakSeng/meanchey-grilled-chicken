"""Inventory: movements from production (finish / reopen / cancel), the no-negative rule,
untracked batches, production-only items, the per-batch breakdown, access, history and
concurrency."""

import asyncio
from decimal import Decimal

import pytest
from sqlalchemy import delete, func, select, update

from app.bootstrap import bootstrap
from app.models import (
    InventoryBalance,
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
    # With Inventory history (Off by default), so these tests can read the movements.
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


async def lower_balance(session, code: str, count: int) -> None:
    """Simulate stock that left by other means (no manual changes exist): a safeguard test."""
    await session.execute(
        update(InventoryBalance).where(InventoryBalance.item_code == code).values(count=count)
    )
    await session.commit()


async def test_negative_guard_refuses_finish_reopen_and_cancel(
    client, api, supplier, superadmin, session
) -> None:
    batch = await api.step1(supplier, 10)
    await lower_balance(session, "chicken", 5)
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

    await lower_balance(session, "chicken", 10)
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
    assert ok(await item(client, gm, "chicken"))["sources"] == []
    batch = ok(await api.patch(batch, "produced", **PRODUCED))
    batch = ok(await api.finish(batch, "produced"))
    batch = ok(await api.reopen(batch, "raw-material"))
    batch = ok(await api.cancel(batch))
    assert await movement_count(session) == 0
    assert batch["inventory_tracked"] is False and batch["stock_changes"] == []


# --- Production items only (no manual changes) ---------------------------------------------------


@pytest.mark.parametrize("code", ["chicken", "packs_big", "byproduct_packed.liver", "wasted.wings"])
async def test_production_items_are_never_set_by_hand(
    client, superadmin, gm, session, code
) -> None:
    for user in (superadmin, gm):
        r = await set_value(client, user, code, count=1, kg="1", reason="Opening stock")
        assert_error(r, 409, "INVENTORY_ITEM_PRODUCTION_ONLY")
        assert r.json()["error"]["details"] == {"item_code": code}
    assert await movement_count(session) == 0
    assert_error(
        await set_value(client, superadmin, "nope", count=1, reason="x"),
        404,
        "INVENTORY_ITEM_NOT_FOUND",
    )


async def test_every_item_comes_from_production(client, gm) -> None:
    assert {i["origin"] for i in (await stock(client, gm)).values()} == {"production"}


async def test_adjust_permission_and_feature_are_gone(client, superadmin, gm, session) -> None:
    assert "inventory_adjust" not in registry.FEATURES_BY_CODE
    assert "inventory.adjust" not in {p.code for p in registry.PERMISSIONS}
    perm = await session.get(Permission, "inventory.adjust")
    assert perm is None or perm.is_active is False
    codes = {
        f["code"]
        for m in ok(await client.get(f"/users/{gm.id}/features", headers=auth(superadmin)))["menus"]
        for f in m["features"]
    }
    assert "inventory_adjust" not in codes


# --- Per-batch breakdown -------------------------------------------------------------------------


def item(client, user, code: str):
    return client.get(f"/inventory/items/{code}", headers=auth(user))


def sources(body: dict) -> list[tuple]:
    return [(s["code"], s["count"], s["kg"], s["last_step"]) for s in body["sources"]]


async def test_breakdown_adds_up_and_follows_production(client, api, supplier, gm, make_user):
    viewer = await make_user(Role.STAFF, perms=["inventory.view"])  # no history needed
    old = await api.step1(supplier, 100)
    new = await api.step1(supplier, 50)

    body = ok(await item(client, viewer, "chicken"))
    assert (body["count"], body["kg"]) == (150, "51.000")
    assert sources(body) == [
        (old["code"], 100, "25.500", 1),
        (new["code"], 50, "25.500", 1),
    ]  # oldest batch first
    assert sum(s["count"] for s in body["sources"]) == body["count"]
    assert "movements" not in body and body["origin"] == "production"

    # Step 2 of the newer batch: its chickens leave, its wings appear.
    new = ok(await api.patch(new, "produced", **PRODUCED))
    new = ok(await api.finish(new, "produced"))
    assert sources(ok(await item(client, viewer, "chicken"))) == [(old["code"], 100, "25.500", 1)]
    assert sources(ok(await item(client, viewer, "wings"))) == [(new["code"], 100, "4.200", 2)]

    # Step 3: wings move into packs and wasted (estimated kg).
    new = await api.confirm_plan(new, 40, 19)
    new = await finish3(api, new, big=40, small=19)
    wings = ok(await item(client, viewer, "wings"))
    assert wings["sources"] == [] and wings["count"] == 0
    assert sources(ok(await item(client, viewer, "packs_big"))) == [(new["code"], 40, None, 3)]
    wasted = ok(await item(client, viewer, "wasted.wings"))
    assert sources(wasted) == [(new["code"], 1, "0.042", 3)]
    assert wasted["sources"][0]["kg_estimated"] is True

    # Reopen step 3: the wings are back with this batch, the packs gone.
    new = ok(await api.reopen(new, "standardize"))
    assert sources(ok(await item(client, viewer, "wings"))) == [(new["code"], 100, "4.200", 2)]
    assert ok(await item(client, viewer, "packs_big"))["sources"] == []

    # Cancel the older batch (still at step 2): it drops out of the chickens.
    ok(await api.cancel(await api.get(old)))
    chicken = ok(await item(client, viewer, "chicken"))
    assert chicken["sources"] == [] and chicken["count"] == 0


async def test_item_detail_access(client, make_user) -> None:
    staff = await make_user(Role.STAFF)
    assert_error(await item(client, staff, "chicken"), 403, "MISSING_PERMISSION")
    viewer = await make_user(Role.STAFF, perms=["inventory.view"])
    assert_error(await item(client, viewer, "nope"), 404, "INVENTORY_ITEM_NOT_FOUND")


# --- History filters -----------------------------------------------------------------------------


async def test_history_filters(client, api, supplier, gm) -> None:
    batch = await api.step2(supplier)
    assert {m["source"] for m in await history(client, gm, source="production")} == {"production"}
    assert await history(client, gm, source="adjustment") == []
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


async def test_steps_by_the_superadmin_read_as_system(client, superadmin, gm, supplier) -> None:
    await Api(client, superadmin).step1(supplier, 3)
    row = (await history(client, gm))[0]
    assert row["created_by"]["is_system"] is True and row["created_by"]["id"] is None
    assert "superadmin" not in str(row).lower()


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
    hist = registry.FEATURES_BY_CODE["inventory_history"]
    assert inv.menu == hist.menu == "workstation"
    assert inv.level_map == {"off": frozenset(), "view": {"inventory.view"}}
    assert hist.applies_to == (Role.GENERAL_MANAGER, Role.SUPERVISOR)
    assert hist.level_map == {"off": frozenset(), "view": {"inventory.history"}}
    assert hist.grantor_must_hold is True
    d = registry.DEFAULT_PERMISSIONS
    assert "inventory.view" in d[Role.GENERAL_MANAGER]
    assert "inventory.history" not in d[Role.GENERAL_MANAGER]  # Off by default
    assert d[Role.SUPERVISOR] & {"inventory.view", "inventory.history"} == {"inventory.view"}
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
    assert features["inventory_history"]["current_level"] == "off"

    # A supervisor (Staff access) gives staff Inventory View, within its own access.
    r = await client.put(
        f"/users/{staff.id}/features/inventory", json={"level": "view"}, headers=auth(sup)
    )
    assert ok(r)["current_level"] == "view"
    ok(await client.get("/inventory", headers=auth(staff)))
    ok(await item(client, staff, "chicken"))

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
    codes = ["inventory.view", "inventory.history"]
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

    # inventory.history is in nobody's defaults: nothing to backfill.
    assert await held(gm) == {"inventory.view"}
    assert await held(sup) == {"inventory.view"}
    assert await held(staff) == set()
