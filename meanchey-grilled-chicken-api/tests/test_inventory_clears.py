"""Clear stock: lines and validation, where the quantity goes (to Wasted or removed), estimated
kg, FIFO attribution (batches and preparations) and breakdowns, impacts (Created orders, step 2 /
3 batches, confirmed plans, draft preparations, reopen) with the dry run and the acknowledgement,
access and defaults, audit, alerts (bell and Telegram), codes and history."""

from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models import AuditLog, InventoryMovement, Language, Notification, Role
from app.permissions import registry
from app.services.production_service import business_today
from tests.conftest import assert_error, auth, set_sachet_stock
from tests.test_orders import Orders, box
from tests.test_preparations import Prep, add_stock, materials
from tests.test_production import Api, ok, standardize_body

REASON = "Spoiled in the freezer"


@pytest.fixture
async def gm(make_user):
    # GM defaults (Inventory clear Full) plus inventory history.
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


def lines(**quantities) -> list[dict]:
    """lines(packs_big=3, liver_packed="0.4"): item codes with dots written as `__`."""
    return [{"item_code": c.replace("__", "."), "quantity": str(q)} for c, q in quantities.items()]


class Clears:
    def __init__(self, client, actor) -> None:
        self.client, self.headers = client, auth(actor)

    def preview(self, items: list[dict]):
        return self.client.post(
            "/inventory/clears/preview", json={"lines": items}, headers=self.headers
        )

    def create_raw(self, items: list[dict], reason: str = REASON, **extra):
        body = {"lines": items, "reason": reason, **extra}
        return self.client.post("/inventory/clears", json=body, headers=self.headers)

    async def create(self, items: list[dict], **extra) -> dict:
        return ok(await self.create_raw(items, **extra), 201)


@pytest.fixture
def clears(client, gm) -> Clears:
    return Clears(client, gm)


async def stock(client, user) -> dict[str, dict]:
    body = ok(await client.get("/inventory", headers=auth(user)))
    return {i["code"]: i for s in body["sections"] for i in s["items"]}


async def breakdown(client, user, code: str) -> list[tuple]:
    body = ok(await client.get(f"/inventory/items/{code}", headers=auth(user)))
    return [(s["code"], s["count"], s["kg"]) for s in body["sources"]] or [
        (s["code"], s["count"], s["kg"], s["g"]) for s in body["preparation_sources"]
    ]


def kinds(impacts: list[dict]) -> list[tuple]:
    return [(i["type"], i["code"], i["item_code"], i["message_key"]) for i in impacts]


# --- Lines and destinations ----------------------------------------------------------------------


async def test_packs_and_packed_byproducts_move_to_wasted(client, gm, api, supplier, clears):
    batch = await api.completed(supplier)  # 7 × 4-piece, 5 × 2-piece, 0.4 kg packed by-products
    items = lines(packs_big=3, byproduct_packed__liver="0.4")

    # Dry run: current / after and the destination; reopening step 3 would no longer work.
    preview = ok(await clears.preview(items))
    by_code = {line["item_code"]: line for line in preview["lines"]}
    assert (by_code["packs_big"]["current"], by_code["packs_big"]["after"]) == ("7", "4")
    assert by_code["packs_big"]["destination"]["item_code"] == "wasted.packs_big"
    assert by_code["byproduct_packed.liver"]["after"] == "0.000"
    assert by_code["byproduct_packed.liver"]["destination"]["item_code"] == "wasted.byproduct.liver"
    assert kinds(preview["impacts"]) == [
        ("reopen", batch["code"], "byproduct_packed.liver", "reopen_batch_blocked"),
        ("reopen", batch["code"], "packs_big", "reopen_batch_blocked"),
    ]
    assert preview["impacts"][1]["step"] == 3
    assert (preview["impacts"][1]["needed"], preview["impacts"][1]["available_after"]) == ("7", "4")

    # Impacts need the acknowledgement; nothing changed meanwhile.
    r = await clears.create_raw(items)
    assert_error(r, 409, "INVENTORY_CLEAR_UNACKNOWLEDGED")
    assert len(r.json()["error"]["details"]["impacts"]) == 2
    assert (await stock(client, gm))["packs_big"]["count"] == 7

    clear = await clears.create(items, acknowledge_impacts=True)
    assert clear["code"] == f"CL-{business_today():%Y%m%d}-001"
    assert clear["reason"] == REASON
    assert clear["created_by"]["full_name"] == "Test general_manager"
    assert [
        (li["item_code"], li["quantity"], li["moved_to"]["item_code"]) for li in clear["lines"]
    ] == [
        ("packs_big", "3", "wasted.packs_big"),
        ("byproduct_packed.liver", "0.400", "wasted.byproduct.liver"),
    ]
    assert len(clear["impacts"]) == 2

    items_now = await stock(client, gm)
    assert items_now["packs_big"]["count"] == 4
    assert items_now["wasted.packs_big"]["count"] == 3
    assert items_now["byproduct_packed.liver"]["kg"] == "0.000"
    assert items_now["wasted.byproduct.liver"]["kg"] == "0.500"  # 0.1 rejected + 0.4 cleared
    # The wasted quantities keep the batch: breakdowns still add up.
    assert await breakdown(client, gm, "wasted.packs_big") == [(batch["code"], 3, None)]
    assert await breakdown(client, gm, "packs_big") == [(batch["code"], 4, None)]

    # The movements: source clear, linked to the clear and the batch.
    r = await client.get("/inventory/movements", params={"clear_id": clear["id"]}, headers=auth(gm))
    rows = ok(r)["items"]
    assert len(rows) == 4
    assert {m["source"] for m in rows} == {"clear"}
    assert {m["clear"]["code"] for m in rows} == {clear["code"]}
    assert {m["batch"]["code"] for m in rows} == {batch["code"]}
    assert {m["reason"] for m in rows} == {None}

    # Reopening step 3 is now refused, naming the clear.
    batch = await api.get(batch)
    r = await api.reopen(batch, "standardize")
    assert_error(r, 409, "PRODUCTION_STOCK_ALREADY_USED")
    assert r.json()["error"]["details"]["clears"] == [clear["code"]]


async def test_wings_by_count_with_estimated_kg(client, gm, api, supplier, clears):
    batch = await api.step2(supplier)  # 20 wings, 4.200 kg; confirmed plan, step 3 a draft
    preview = ok(await clears.preview(lines(wings=5)))
    line = preview["lines"][0]
    assert (line["after"], line["kg"], line["kg_estimated"]) == ("15", "1.050", True)
    assert line["destination"]["item_code"] == "wasted.wings"
    # Step 3 waits for the batch's own 20 wings.
    assert kinds(preview["impacts"]) == [
        ("production", batch["code"], "wings", "production_step3_short")
    ]
    assert (preview["impacts"][0]["needed"], preview["impacts"][0]["available_after"]) == (
        "20",
        "15",
    )

    await clears.create(lines(wings=5), acknowledge_impacts=True)
    items = await stock(client, gm)
    assert (items["wings"]["count"], items["wings"]["kg"]) == (15, "3.150")
    assert (items["wasted.wings"]["count"], items["wasted.wings"]["kg"]) == (5, "1.050")

    # The rest: all of the batch's remaining kg, no rounding left over.
    clear = await clears.create(lines(wings=15), acknowledge_impacts=True)
    assert clear["code"].endswith("-002")
    assert (clear["lines"][0]["quantity"], clear["lines"][0]["kg"]) == ("15", "3.150")
    items = await stock(client, gm)
    assert (items["wings"]["count"], items["wings"]["kg"]) == (0, "0.000")
    assert (items["wasted.wings"]["count"], items["wasted.wings"]["kg"]) == (20, "4.200")


async def test_chicken_materials_prepared_and_wasted_are_removed(
    client, gm, api, supplier, clears, session
):
    batch = await api.step1(supplier)  # 10 chickens, 25.500 kg; step 2 a draft
    ms = await materials(client, gm)
    string = ms["String"]
    await add_stock(client, gm, string, "5")
    await set_sachet_stock(session, 20, 100)  # the completed batch uses 7 and 5
    completed = await api.completed(supplier)  # 1 wasted wing (≈0.210 kg)

    items = lines(
        chicken=4,
        **{string["item_code"]: "1.5"},
        satay_sachet_4=3,
        wasted__wings=1,
    )
    preview = ok(await clears.preview(items))
    assert all(line["destination"] is None for line in preview["lines"])
    impacts = kinds(preview["impacts"])
    assert ("production", batch["code"], "chicken", "production_step2_short") in impacts
    assert ("reopen", completed["code"], "wasted.wings", "reopen_batch_blocked") in impacts

    clear = await clears.create(items, acknowledge_impacts=True)
    assert all(li["moved_to"] is None for li in clear["lines"])
    after = await stock(client, gm)
    assert (after["chicken"]["count"], after["chicken"]["kg"]) == (6, "15.300")
    assert after[string["item_code"]]["kg"] == "3.500"
    assert after["satay_sachet_4"]["count"] == 10
    assert (after["wasted.wings"]["count"], after["wasted.wings"]["kg"]) == (0, "0.000")
    assert await breakdown(client, gm, "chicken") == [(batch["code"], 6, "15.300")]


async def test_validation(client, gm, api, supplier, clears):
    await api.completed(supplier)
    r = await clears.create_raw(lines(packs_big=8))
    assert_error(r, 409, "INVENTORY_INSUFFICIENT")
    entry = r.json()["error"]["details"]["items"][0]
    assert (entry["item_code"], entry["available_count"], entry["needed_count"]) == (
        "packs_big",
        7,
        8,
    )
    assert_error(await clears.preview(lines(packs_big=8)), 409, "INVENTORY_INSUFFICIENT")
    for bad in (
        lines(packs_big=0),
        lines(packs_big="1.5"),
        lines(byproduct_packed__liver="0.0001"),
    ):
        assert_error(await clears.create_raw(bad), 422, "VALIDATION_ERROR")
    assert_error(await clears.create_raw(lines(packs_big=1), reason="  "), 422, "VALIDATION_ERROR")
    assert_error(
        await clears.create_raw(lines(packs_big=1), reason="x" * 501), 422, "VALIDATION_ERROR"
    )
    r = await clears.create_raw([*lines(packs_big=1), *lines(packs_big=2)])
    assert_error(r, 422, "VALIDATION_ERROR")
    assert_error(await clears.create_raw([]), 422, "VALIDATION_ERROR")
    assert_error(await clears.create_raw(lines(nothing=1)), 404, "INVENTORY_ITEM_NOT_FOUND")
    # Nothing was written.
    assert ok(await client.get("/inventory/clears", headers=auth(gm)))["total"] == 0
    assert (await stock(client, gm))["packs_big"]["count"] == 7


# --- FIFO ----------------------------------------------------------------------------------------


async def test_oldest_batch_first_and_breakdowns_add_up(client, gm, api, supplier, clears):
    first = await api.completed(supplier)
    second = await api.completed(supplier)
    await clears.create(lines(packs_big=10), acknowledge_impacts=True)
    assert await breakdown(client, gm, "packs_big") == [(second["code"], 4, None)]
    assert await breakdown(client, gm, "wasted.packs_big") == [
        (first["code"], 7, None),
        (second["code"], 3, None),
    ]
    items = await stock(client, gm)
    assert (items["packs_big"]["count"], items["wasted.packs_big"]["count"]) == (4, 10)

    # Clearing the wasted packs removes them, oldest batch first too.
    await clears.create(lines(wasted__packs_big=8), acknowledge_impacts=True)
    assert await breakdown(client, gm, "wasted.packs_big") == [(second["code"], 2, None)]


async def test_prepared_items_by_preparation(client, gm, clears):
    prep = Prep(client, gm)
    ms = await materials(client, gm)
    string = ms["String"]
    await add_stock(client, gm, string, "5")
    p1 = await prep.finished("packaging_material", [{"material_id": string["id"], "quantity": "1"}])
    p2 = await prep.finished("packaging_material", [{"material_id": string["id"], "quantity": "2"}])
    twin = f"{string['item_code']}_prepared"

    preview = ok(await clears.preview(lines(**{twin: "1.5"})))
    # p1 gives all of its 1 kg (it could no longer be reopened), p2 0.5 of its 2 kg.
    assert kinds(preview["impacts"]) == [
        ("reopen", p1["code"], twin, "reopen_preparation_blocked"),
        ("reopen", p2["code"], twin, "reopen_preparation_blocked"),
    ]
    await clears.create(lines(**{twin: "1.5"}), acknowledge_impacts=True)
    assert await breakdown(client, gm, twin) == [(p2["code"], None, "1.500", None)]
    assert (await stock(client, gm))[twin]["kg"] == "1.500"
    # p1 gave its prepared stock away: it can no longer be reopened.
    r = await prep.action(await prep.get(p1), "reopen")
    assert_error(r, 409, "INVENTORY_INSUFFICIENT")
    assert r.json()["error"]["details"]["items"][0]["available_kg"] == "0.000"


# --- Impacts -------------------------------------------------------------------------------------


async def test_created_orders(client, gm, api, supplier, clears):
    await api.completed(supplier)
    await api.completed(supplier)  # 14 × 4-piece
    customer = ok(await client.post("/customers", json={"name": "Dara"}, headers=auth(gm)), 201)
    orders = Orders(client, gm)
    small = await orders.create(customer, [box(packs_big=4)])
    big = await orders.create(customer, [box(packs_big=10)])

    # 14 - 6 = 8 left: the order of 10 would fail at Delivering, the order of 4 wouldn't.
    preview = ok(await clears.preview(lines(packs_big=6)))
    order_impacts = [i for i in preview["impacts"] if i["type"] == "order"]
    assert [(i["code"], i["needed"], i["available_after"]) for i in order_impacts] == [
        (big["code"], "10", "8")
    ]
    assert order_impacts[0]["id"] == big["id"]
    assert order_impacts[0]["message_key"] == "order_short"
    clear = await clears.create(lines(packs_big=6), acknowledge_impacts=True)
    assert [i["code"] for i in clear["impacts"] if i["type"] == "order"] == [big["code"]]
    assert_error(await orders.delivering(big), 409, "INVENTORY_INSUFFICIENT")
    ok(await orders.delivering(small))


async def test_plans_step3_and_marinade(client, gm, api, supplier, clears, session):
    await set_sachet_stock(session, 10, 10)
    batch = await api.step2(supplier)  # confirmed plan: 7 × 4-piece, 5 × 2-piece
    # Step 3 has no sachet counts yet: the plan's packs are what will be needed.
    preview = ok(await clears.preview(lines(satay_sachet_4=5)))
    assert kinds(preview["impacts"]) == [
        ("plan", batch["code"], "satay_sachet_4", "plan_sachets_short")
    ]
    # Once step 3 has its counts (auto: one per pack), it's the batch itself.
    ok(await api.patch(batch, "standardize", **standardize_body()))
    preview = ok(await clears.preview(lines(satay_sachet_4=5)))
    assert kinds(preview["impacts"]) == [
        ("production", batch["code"], "satay_sachet_4", "production_step3_short")
    ]
    # Processed by-products: step 3 takes carry + rejected (0.5) of the batch's own.
    preview = ok(await clears.preview(lines(byproduct_processed__liver="0.1")))
    assert kinds(preview["impacts"]) == [
        ("production", batch["code"], "byproduct_processed.liver", "production_step3_short")
    ]

    # Step 2 drafts need their marinade (350 g each).
    waiting = await api.step1(supplier)
    ok(await api.patch(waiting, "produced", marinade_g="350"))
    marinade = next(m for m in (await materials(client, gm)).values() if m["system_code"])
    on_hand = Decimal((await stock(client, gm))[marinade["item_code"]]["g"])
    preview = ok(await clears.preview(lines(**{marinade["item_code"]: on_hand - 100})))
    assert kinds(preview["impacts"]) == [
        ("production", waiting["code"], marinade["item_code"], "production_step2_short")
    ]
    assert preview["impacts"][0]["available_after"] == "100.0"
    # No impacts: no acknowledgement needed.
    ok(await clears.create_raw(lines(satay_sachet_2=1)), 201)


async def test_draft_preparations(client, gm, clears):
    prep = Prep(client, gm)
    ms = await materials(client, gm)
    string = ms["String"]
    await add_stock(client, gm, string, "5")
    draft = await prep.create("packaging_material")
    ok(await prep.save(draft, lines=[{"material_id": string["id"], "quantity": "3"}]))
    preview = ok(await clears.preview(lines(**{string["item_code"]: "2.5"})))
    assert kinds(preview["impacts"]) == [
        ("preparation", draft["code"], string["item_code"], "preparation_short")
    ]
    assert (preview["impacts"][0]["needed"], preview["impacts"][0]["available_after"]) == (
        "3.000",
        "2.500",
    )
    assert ok(await clears.preview(lines(**{string["item_code"]: "2"})))["impacts"] == []


# --- Access, defaults, alerts, audit -------------------------------------------------------------


def test_registry_levels_and_defaults() -> None:
    feature = registry.FEATURES_BY_CODE["inventory_clear"]
    assert feature.menu == "workstation"
    assert feature.applies_to == (Role.GENERAL_MANAGER, Role.SUPERVISOR)
    assert feature.level_map["full"] == frozenset({"inventory.clear"})
    assert "inventory.clear" in registry.DEFAULT_PERMISSIONS[Role.GENERAL_MANAGER]
    assert "inventory.clear" not in registry.DEFAULT_PERMISSIONS[Role.SUPERVISOR]
    assert "inventory.clear" not in registry.DEFAULT_PERMISSIONS[Role.STAFF]


async def test_access(client, gm, api, supplier, superadmin, make_user):
    await api.completed(supplier)
    supervisor = await make_user(Role.SUPERVISOR)
    sup = Clears(client, supervisor)
    assert_error(await sup.preview(lines(packs_big=1)), 403, "MISSING_PERMISSION")
    assert_error(await sup.create_raw(lines(packs_big=1)), 403, "MISSING_PERMISSION")
    assert_error(
        await client.get("/inventory/clears", headers=auth(supervisor)), 403, "MISSING_PERMISSION"
    )

    # The GM gives it to the supervisor (normal rules).
    r = await client.put(
        f"/users/{supervisor.id}/features/inventory_clear", json={"level": "full"}, headers=auth(gm)
    )
    ok(r)
    clear = await sup.create(lines(packs_big=1), acknowledge_impacts=True)
    ok(await client.get(f"/inventory/clears/{clear['id']}", headers=auth(supervisor)))

    # inventory.history alone reads the records.
    reader = await make_user(Role.SUPERVISOR, perms=["inventory.view", "inventory.history"])
    page = ok(await client.get("/inventory/clears", headers=auth(reader)))
    assert [c["code"] for c in page["items"]] == [clear["code"]]
    assert_error(
        await Clears(client, reader).preview(lines(packs_big=1)), 403, "MISSING_PERMISSION"
    )

    # The superadmin can turn it off for a GM.
    r = await client.put(
        f"/users/{gm.id}/features/inventory_clear", json={"level": "off"}, headers=auth(superadmin)
    )
    ok(r)
    assert_error(await Clears(client, gm).preview(lines(packs_big=1)), 403, "MISSING_PERMISSION")
    ok(await Clears(client, superadmin).preview(lines(packs_big=1)))
    unknown = "00000000-0000-0000-0000-000000000000"
    assert_error(
        await client.get(f"/inventory/clears/{unknown}", headers=auth(reader)),
        404,
        "INVENTORY_CLEAR_NOT_FOUND",
    )


async def test_alerts_audit_and_list(client, gm, api, supplier, make_user, superadmin, session):
    await api.completed(supplier)
    customer = ok(await client.post("/customers", json={"name": "Dara"}, headers=auth(gm)), 201)
    await Orders(client, gm).create(customer, [box(packs_big=7)])
    # Only who can open the record: a GM without Inventory clear or history gets nothing.
    other_gm = await make_user(Role.GENERAL_MANAGER, perms=["inventory.view"])
    holder = await make_user(Role.SUPERVISOR, perms=["inventory.view", "inventory.clear"])
    reader = await make_user(Role.SUPERVISOR, perms=["inventory.view", "inventory.history"])
    bystander = await make_user(Role.SUPERVISOR)

    clear = await Clears(client, gm).create(
        lines(packs_big=2, byproduct_packed__liver="0.4"), acknowledge_impacts=True
    )
    rows = list(
        await session.scalars(select(Notification).where(Notification.type == "inventory.cleared"))
    )
    assert {r.user_id for r in rows} == {gm.id, holder.id, reader.id, superadmin.id}
    assert not {other_gm.id, bystander.id} & {r.user_id for r in rows}
    payload = rows[0].payload
    assert payload["code"] == clear["code"]
    assert payload["impacts"] == {"order": 1, "reopen": 1}
    assert payload["items"][0] == {
        "name_en": "4-Piece Packs",
        "name_km": "កញ្ចប់ ៤ ដុំ",
        "quantity": "2",
        "unit": "count",
    }

    from app.bot.notify import message_for

    en, keyboard = message_for(rows[0], Language.EN, "Sokha")
    assert en == (
        f"🧹 Sokha cleared stock <b>{clear['code']}</b>: 4-Piece Packs 2, Liver (packed) 0.400 kg"
        f" — “{REASON}”. Affects 1 order, 1 step that can't be reopened."
    )
    km, _ = message_for(rows[0], Language.KM, None)
    assert km.startswith("🧹 ប្រព័ន្ធ បានសម្អាតស្តុក")
    assert keyboard is None or "/workstation/inventory/clears/" in str(keyboard)

    # The bell: the actor is a UserRef.
    bell = ok(await client.get("/notifications", headers=auth(holder)))["items"][0]
    assert bell["type"] == "inventory.cleared"
    assert bell["actor"]["full_name"] == "Test general_manager"
    assert "actor_id" not in bell["payload"]

    log = await session.scalar(select(AuditLog).where(AuditLog.action == "inventory.clear"))
    assert log.entity_type == "inventory_clear"
    assert log.details["code"] == clear["code"]
    assert log.details["reason"] == REASON
    assert [line["item_code"] for line in log.details["lines"]] == [
        "packs_big",
        "byproduct_packed.liver",
    ]

    today = business_today().isoformat()
    page = ok(
        await client.get(
            "/inventory/clears", params={"date_from": today, "date_to": today}, headers=auth(gm)
        )
    )
    assert [c["code"] for c in page["items"]] == [clear["code"]]
    page = ok(
        await client.get("/inventory/clears", params={"date_to": "2020-01-01"}, headers=auth(gm))
    )
    assert page["total"] == 0
    count = await session.scalar(
        select(InventoryMovement.id).where(InventoryMovement.source == "clear").limit(1)
    )
    assert count is not None
