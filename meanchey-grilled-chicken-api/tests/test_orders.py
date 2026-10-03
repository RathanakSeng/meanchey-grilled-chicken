"""Orders: access and defaults, create / edit validation, cancel, Delivering (stock out, oldest
batch first), Delivered, returns and their review (stock / wasted, batch attribution), the
production guard, codes, stats, list, options and audit."""

import asyncio
import re

import pytest
from sqlalchemy import delete, select, update

from app.bootstrap import bootstrap
from app.models import AuditLog, Customer, InventoryMovement, Permission, Role, UserPermission
from app.permissions import registry
from app.services.production_service import business_today
from tests.conftest import assert_error, auth
from tests.test_production import Api, ok

ORDER_CODES = ["orders.view", "orders.create", "orders.update", "orders.cancel"]
ALL_ORDER_CODES = [*ORDER_CODES, "orders.review_returns"]


@pytest.fixture
async def gm(make_user):
    # GM defaults (Orders Record, management and returns Full) plus inventory history.
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


@pytest.fixture
async def customer(client, gm) -> dict:
    body = {"name": "Dara Shop", "location": "Phsar Thmei"}
    return ok(await client.post("/customers", json=body, headers=auth(gm)), 201)


def box(color: str = "white", **items) -> dict:
    """box("white", packs_big=2, liver="0.2"): packs by count, by-products (packed) by kg."""
    lines = []
    for code, qty in items.items():
        if code in ("packs_big", "packs_small"):
            lines.append({"item_code": code, "count": qty})
        else:
            lines.append({"item_code": f"byproduct_packed.{code}", "kg": qty})
    return {"color": color, "lines": lines}


class Orders:
    def __init__(self, client, actor) -> None:
        self.client, self.headers = client, auth(actor)

    def create_raw(self, customer: dict, boxes: list[dict], **extra):
        body = {"customer_id": customer["id"], "boxes": boxes, **extra}
        return self.client.post("/orders", json=body, headers=self.headers)

    async def create(self, customer: dict, boxes: list[dict], **extra) -> dict:
        return ok(await self.create_raw(customer, boxes, **extra), 201)

    async def get(self, order: dict) -> dict:
        return ok(await self.client.get(f"/orders/{order['id']}", headers=self.headers))

    def patch(self, order: dict, version: int | None = None, **fields):
        body = {"version": order["version"] if version is None else version, **fields}
        return self.client.patch(f"/orders/{order['id']}", json=body, headers=self.headers)

    def cancel(self, order: dict, reason: str = "Customer cancelled"):
        body = {"version": order["version"], "reason": reason}
        return self.client.post(f"/orders/{order['id']}/cancel", json=body, headers=self.headers)

    def delivering(self, order: dict, version: int | None = None):
        body = {"version": order["version"] if version is None else version}
        return self.client.post(
            f"/orders/{order['id']}/delivering", json=body, headers=self.headers
        )

    def delivered(self, order: dict, outcome: str = "accepted", **extra):
        body = {"version": order["version"], "outcome": outcome, **extra}
        return self.client.post(f"/orders/{order['id']}/delivered", json=body, headers=self.headers)

    def review(self, order: dict, items: list[dict]):
        body = {"version": order["version"], "items": items}
        return self.client.post(
            f"/orders/{order['id']}/returns/review", json=body, headers=self.headers
        )


@pytest.fixture
def orders(client, gm) -> Orders:
    return Orders(client, gm)


async def stock(client, user) -> dict[str, dict]:
    body = ok(await client.get("/inventory", headers=auth(user)))
    return {i["code"]: i for s in body["sections"] for i in s["items"]}


async def sources(client, user, code: str) -> list[tuple[str, int | None, str | None]]:
    body = ok(await client.get(f"/inventory/items/{code}", headers=auth(user)))
    return [(s["code"], s["count"], s["kg"]) for s in body["sources"]]


async def two_batches(api: Api, supplier: dict) -> tuple[dict, dict]:
    """Two completed batches, oldest first: 7 × 4-Piece, 5 × 2-Piece, 0.4 kg of each packed
    by-product each."""
    first = await api.completed(supplier)
    second = await api.completed(supplier)
    return first, second


# --- Access, defaults, backfill ------------------------------------------------------------------


def test_registry_levels_and_defaults() -> None:
    f = registry.FEATURES_BY_CODE
    assert f["orders"].level_map == {
        "off": frozenset(),
        "view": {"orders.view"},
        "record": {"orders.view", "orders.create"},
    }
    assert f["order_management"].level_map["full"] == {"orders.update", "orders.cancel"}
    assert f["order_returns"].level_map["full"] == {"orders.review_returns"}
    assert Role.STAFF in f["orders"].applies_to
    assert Role.STAFF not in f["order_management"].applies_to
    assert Role.STAFF not in f["order_returns"].applies_to
    defaults = registry.DEFAULT_PERMISSIONS
    assert set(ALL_ORDER_CODES) <= defaults[Role.GENERAL_MANAGER]
    assert {c for c in defaults[Role.SUPERVISOR] if c.startswith("orders.")} == {
        "orders.view",
        "orders.create",
    }
    assert not {c for c in defaults[Role.STAFF] if c.startswith("orders.")}


async def test_backfill_follows_the_defaults(session, make_user) -> None:
    gm = await make_user(Role.GENERAL_MANAGER)
    sup = await make_user(Role.SUPERVISOR)
    staff = await make_user(Role.STAFF)
    await session.execute(
        delete(UserPermission).where(UserPermission.permission_code.in_(ALL_ORDER_CODES))
    )
    await session.execute(delete(Permission).where(Permission.code.in_(ALL_ORDER_CODES)))
    await session.commit()

    await bootstrap(session)

    async def held(user) -> set[str]:
        return set(
            await session.scalars(
                select(UserPermission.permission_code).where(
                    UserPermission.user_id == user.id,
                    UserPermission.permission_code.in_(ALL_ORDER_CODES),
                )
            )
        )

    assert await held(gm) == set(ALL_ORDER_CODES)
    assert await held(sup) == {"orders.view", "orders.create"}
    assert await held(staff) == set()


async def test_staff_off_by_default_and_view_only_cannot_create(
    client, gm, make_user, customer
) -> None:
    staff = await make_user(Role.STAFF)
    assert_error(await client.get("/orders", headers=auth(staff)), 403, "MISSING_PERMISSION")
    r = await client.put(
        f"/users/{staff.id}/features/orders", json={"level": "view"}, headers=auth(gm)
    )
    assert r.status_code == 200, r.text
    assert ok(await client.get("/orders", headers=auth(staff)))["total"] == 0
    assert_error(
        await Orders(client, staff).create_raw(customer, [box(packs_big=1)]),
        403,
        "MISSING_PERMISSION",
    )
    assert_error(
        await client.get("/orders/customer-options", headers=auth(staff)),
        403,
        "MISSING_PERMISSION",
    )


async def test_supervisor_cap_for_staff_orders(client, gm, make_user) -> None:
    sup = await make_user(Role.SUPERVISOR)  # Orders Record by default, with Staff access
    staff = await make_user(Role.STAFF)
    r = await client.put(
        f"/users/{staff.id}/features/orders", json={"level": "record"}, headers=auth(sup)
    )
    assert r.status_code == 200, r.text
    # Lowered to View only: Record is above the supervisor's own access now.
    r = await client.put(
        f"/users/{sup.id}/features/orders", json={"level": "view"}, headers=auth(gm)
    )
    assert r.status_code == 200, r.text
    assert_error(
        await client.put(
            f"/users/{staff.id}/features/orders", json={"level": "record"}, headers=auth(sup)
        ),
        403,
        "PERMISSION_NOT_HELD",
    )


async def test_staff_with_record_creates_and_delivers_but_cannot_edit_or_review(
    client, gm, make_user, api, supplier, customer
) -> None:
    await api.completed(supplier)
    staff = await make_user(Role.STAFF, perms=["orders.view", "orders.create"])
    s = Orders(client, staff)
    # The form's pickers need no Customers access.
    options = ok(await client.get("/orders/customer-options", headers=auth(staff)))
    assert [o["name"] for o in options] == ["Dara Shop"]
    order = await s.create(customer, [box(packs_big=1)])
    assert_error(await s.patch(order, note="x"), 403, "MISSING_PERMISSION")
    assert_error(await s.cancel(order), 403, "MISSING_PERMISSION")
    order = ok(await s.delivering(order))
    order = ok(
        await s.delivered(
            order, "returned", reason="Torn", items=[{"item_code": "packs_big", "count": 1}]
        )
    )
    assert order["status"] == "return_pending"
    assert_error(
        await s.review(order, [{"item_code": "packs_big", "to_stock_count": 1}]),
        403,
        "MISSING_PERMISSION",
    )


# --- Create and edit -----------------------------------------------------------------------------


async def test_create_order_with_boxes_and_summary(
    client, session, gm, orders, api, supplier, customer
) -> None:
    order = await orders.create(
        customer,
        [
            box("white", packs_big=2, packs_small=1, liver="0.150"),
            box("white", packs_big=3),
            box("black", packs_small=2, gizzard="0.2"),
        ],
        note="  Call before arriving  ",
    )
    today = business_today()
    assert re.fullmatch(rf"OR-{today:%Y%m%d}-001", order["code"])
    assert order["status"] == "created"
    assert order["delivery_date"] == today.isoformat()
    assert order["note"] == "Call before arriving"
    assert order["customer"]["name"] == "Dara Shop"
    assert order["driver"] is None
    assert order["version"] == 1
    assert [(b["color"], b["position"]) for b in order["boxes"]] == [
        ("white", 1),
        ("white", 2),
        ("black", 3),
    ]
    line = order["boxes"][0]["lines"][2]
    assert (line["item_code"], line["unit"], line["count"], line["kg"]) == (
        "byproduct_packed.liver",
        "kg",
        None,
        "0.150",
    )

    def items(summary) -> dict:
        return {i["item_code"]: i["count"] or i["kg"] for i in summary["items"]}

    white, black = order["summary"]["colors"]
    assert (white["color"], white["boxes"]) == ("white", 2)
    assert items(white) == {"packs_big": 5, "packs_small": 1, "byproduct_packed.liver": "0.150"}
    assert (black["color"], black["boxes"]) == ("black", 1)
    assert items(black) == {"packs_small": 2, "byproduct_packed.gizzard": "0.200"}
    total = order["summary"]["total"]
    assert total["boxes"] == 3
    # Catalog order: 4-Piece, 2-Piece, then the by-products.
    assert [i["item_code"] for i in total["items"]] == [
        "packs_big",
        "packs_small",
        "byproduct_packed.gizzard",
        "byproduct_packed.liver",
    ]
    # Nothing in stock yet: a warning per item (create only warns).
    warnings = {w["item_code"]: w for w in order["stock_warnings"]}
    assert warnings["packs_big"]["available_count"] == 0
    assert warnings["packs_big"]["needed_count"] == 5
    assert warnings["byproduct_packed.liver"]["needed_kg"] == "0.150"

    await api.completed(supplier)  # 7 big, 5 small, 0.4 kg of each by-product
    again = await orders.get(order)
    assert again["stock_warnings"] == []

    log = await session.scalar(select(AuditLog).where(AuditLog.action == "order.create"))
    assert log.entity_type == "order"
    assert log.details["code"] == order["code"]
    assert log.details["white_boxes"] == 2 and log.details["black_boxes"] == 1


@pytest.mark.parametrize(
    ("boxes", "loc"),
    [
        ([], ["body", "boxes"]),
        ([{"color": "white", "lines": []}], ["body", "boxes", "0", "lines"]),
        (
            [{"color": "white", "lines": [{"item_code": "wings", "count": 2}]}],
            ["body", "boxes", "0", "lines", "0", "item_code"],
        ),
        (
            [{"color": "white", "lines": [{"item_code": "packs_big", "kg": "1"}]}],
            ["body", "boxes", "0", "lines", "0", "kg"],
        ),
        (
            [{"color": "white", "lines": [{"item_code": "packs_big", "count": 0}]}],
            ["body", "boxes", "0", "lines", "0", "count"],
        ),
        (
            [{"color": "black", "lines": [{"item_code": "byproduct_packed.liver", "count": 1}]}],
            ["body", "boxes", "0", "lines", "0", "count"],
        ),
        (
            [{"color": "black", "lines": [{"item_code": "byproduct_packed.liver", "kg": "0"}]}],
            ["body", "boxes", "0", "lines", "0", "kg"],
        ),
        (
            [
                box(packs_big=1),
                {
                    "color": "white",
                    "lines": [
                        {"item_code": "packs_big", "count": 1},
                        {"item_code": "packs_big", "count": 2},
                    ],
                },
            ],
            ["body", "boxes", "1", "lines", "1", "item_code"],
        ),
    ],
)
async def test_create_validation(orders, customer, boxes, loc) -> None:
    r = await orders.create_raw(customer, boxes)
    assert_error(r, 422, "VALIDATION_ERROR")
    assert loc in [f["loc"] for f in r.json()["error"]["details"]["fields"]]


async def test_create_rejects_bad_colour_and_extra_fields(orders, customer) -> None:
    r = await orders.create_raw(customer, [{"color": "red", "lines": []}])
    assert_error(r, 422, "VALIDATION_ERROR")
    r = await orders.create_raw(customer, [box(packs_big=1)], status="success")
    assert_error(r, 422, "VALIDATION_ERROR")


async def test_customer_and_driver_rules(client, session, gm, orders, customer, make_user) -> None:
    other = ok(await client.post("/customers", json={"name": "Old Shop"}, headers=auth(gm)), 201)
    await session.execute(
        update(Customer).where(Customer.id == other["id"]).values(is_active=False)
    )
    await session.commit()
    assert_error(await orders.create_raw(other, [box(packs_big=1)]), 422, "CUSTOMER_INACTIVE")
    assert_error(
        await orders.create_raw({"id": "00000000-0000-0000-0000-000000000000"}, [box(packs_big=1)]),
        422,
        "CUSTOMER_NOT_FOUND",
    )
    driver = await make_user(Role.STAFF)
    gone = await make_user(Role.STAFF, is_active=False)
    for bad in (gm, gone):
        r = await orders.create_raw(customer, [box(packs_big=1)], driver_id=str(bad.id))
        assert_error(r, 422, "DRIVER_NOT_ALLOWED")
    order = await orders.create(customer, [box(packs_big=1)], driver_id=str(driver.id))
    assert order["driver"]["id"] == str(driver.id)

    options = ok(await client.get("/orders/driver-options", headers=auth(gm)))
    assert [o["id"] for o in options] == [str(driver.id)]
    customers = ok(await client.get("/orders/customer-options", headers=auth(gm)))
    assert [c["name"] for c in customers] == ["Dara Shop"]  # deactivated left out


async def test_edit_replaces_boxes_and_records_a_diff(
    client, session, gm, orders, customer, make_user
) -> None:
    order = await orders.create(customer, [box(packs_big=2), box("black", packs_small=1)])
    driver = await make_user(Role.SUPERVISOR)
    order = ok(
        await orders.patch(
            order,
            boxes=[box("black", heart="0.3")],
            driver_id=str(driver.id),
            delivery_date="2026-12-01",
        )
    )
    assert order["version"] == 2
    assert [(b["color"], b["position"]) for b in order["boxes"]] == [("black", 1)]
    assert order["driver"]["id"] == str(driver.id)
    assert order["delivery_date"] == "2026-12-01"

    log = await session.scalar(select(AuditLog).where(AuditLog.action == "order.update"))
    changes = log.details["changes"]
    assert set(changes) == {"boxes", "driver", "delivery_date"}
    assert changes["boxes"]["from"]["white"] == 1
    assert changes["boxes"]["to"] == {
        "white": 0,
        "black": 1,
        "items": {"byproduct_packed.heart": "0.300"},
    }

    # Stale version: 409 with the current order.
    r = await orders.patch(order, version=1, note="late")
    assert_error(r, 409, "ORDER_CONFLICT")
    assert r.json()["error"]["details"]["order"]["version"] == 2
    # Invalid boxes: nothing changes.
    assert_error(await orders.patch(order, boxes=[]), 422, "VALIDATION_ERROR")
    assert (await orders.get(order))["version"] == 2


async def test_edit_needs_the_permission_and_a_created_order(
    client, make_user, orders, api, supplier, customer
) -> None:
    await api.completed(supplier)
    sup = await make_user(Role.SUPERVISOR)  # Orders Record, management Off
    order = await orders.create(customer, [box(packs_big=1)])
    assert_error(await Orders(client, sup).patch(order, note="x"), 403, "MISSING_PERMISSION")
    order = ok(await orders.delivering(order))
    r = await orders.patch(order, note="x")
    assert_error(r, 409, "ORDER_INVALID_STATUS")
    assert r.json()["error"]["details"]["status"] == "delivering"


# --- Cancel --------------------------------------------------------------------------------------


async def test_cancel_only_created_with_a_reason(
    client, session, make_user, orders, api, supplier, customer
) -> None:
    order = await orders.create(customer, [box(packs_big=1)])
    sup = await make_user(Role.SUPERVISOR)
    assert_error(await Orders(client, sup).cancel(order), 403, "MISSING_PERMISSION")
    assert_error(await orders.cancel(order, reason="   "), 422, "VALIDATION_ERROR")
    cancelled = ok(await orders.cancel(order))
    assert cancelled["status"] == "cancelled"
    assert cancelled["cancel_reason"] == "Customer cancelled"
    assert cancelled["cancelled_at"] is not None
    assert cancelled["stock_warnings"] == []
    assert_error(await orders.delivering(cancelled), 409, "ORDER_INVALID_STATUS")

    await api.completed(supplier)
    sent = ok(await orders.delivering(await orders.create(customer, [box(packs_big=1)])))
    assert_error(await orders.cancel(sent), 409, "ORDER_INVALID_STATUS")
    log = await session.scalar(select(AuditLog).where(AuditLog.action == "order.cancel"))
    assert log.details["reason"] == "Customer cancelled"


# --- Delivering: stock out, oldest batch first ---------------------------------------------------


async def test_delivering_takes_stock_oldest_batch_first(
    client, gm, orders, api, supplier, customer
) -> None:
    first, second = await two_batches(api, supplier)
    order = await orders.create(
        customer,
        [box("white", packs_big=6, liver="0.3"), box("black", packs_big=4, liver="0.2")],
    )
    order = ok(await orders.delivering(order))
    assert order["status"] == "delivering"
    assert order["delivering_by"]["id"] == str(gm.id)
    assert order["stock_warnings"] == []

    items = await stock(client, gm)
    assert items["packs_big"]["count"] == 4  # 14 - 10
    assert items["byproduct_packed.liver"]["kg"] == "0.300"  # 0.8 - 0.5
    # The oldest batch gave everything it had first; the breakdown still adds up.
    assert await sources(client, gm, "packs_big") == [(second["code"], 4, None)]
    assert await sources(client, gm, "byproduct_packed.liver") == [(second["code"], None, "0.300")]
    assert await sources(client, gm, "packs_small") == [
        (first["code"], 5, None),
        (second["code"], 5, None),
    ]

    moves = ok(
        await client.get("/inventory/movements", params={"order_id": order["id"]}, headers=auth(gm))
    )["items"]
    by_item = {}
    for m in moves:
        assert m["source"] == "order"
        assert m["order"] == {"id": order["id"], "code": order["code"]}
        by_item.setdefault(m["item_code"], []).append(
            (m["batch"]["code"], m["count_delta"] or m["kg_delta"])
        )
    assert sorted(by_item["packs_big"]) == sorted([(first["code"], -7), (second["code"], -3)])
    assert sorted(by_item["byproduct_packed.liver"]) == sorted(
        [(first["code"], "-0.400"), (second["code"], "-0.100")]
    )


async def test_not_enough_stock_keeps_the_order_created(
    client, session, gm, orders, api, supplier, customer
) -> None:
    await api.completed(supplier)  # 7 big
    order = await orders.create(customer, [box(packs_big=5), box("black", packs_big=4)])
    warnings = order["stock_warnings"]
    assert [(w["item_code"], w["available_count"], w["needed_count"]) for w in warnings] == [
        ("packs_big", 7, 9)
    ]
    r = await orders.delivering(order)
    assert_error(r, 409, "INVENTORY_INSUFFICIENT")
    (short,) = r.json()["error"]["details"]["items"]
    assert (short["item_code"], short["available_count"], short["needed_count"]) == (
        "packs_big",
        7,
        9,
    )
    assert short["name_en"] == "4-Piece Packs"
    again = await orders.get(order)
    assert (again["status"], again["version"]) == ("created", 1)
    assert (await stock(client, gm))["packs_big"]["count"] == 7
    count = await session.scalar(
        select(InventoryMovement.id).where(InventoryMovement.source == "order").limit(1)
    )
    assert count is None


async def test_delivering_version_conflict(orders, api, supplier, customer) -> None:
    await api.completed(supplier)
    order = await orders.create(customer, [box(packs_big=1)])
    edited = ok(await orders.patch(order, note="Ring twice"))
    r = await orders.delivering(order)  # version 1, the order is at 2
    assert_error(r, 409, "ORDER_CONFLICT")
    assert r.json()["error"]["details"]["order"]["note"] == "Ring twice"
    assert ok(await orders.delivering(edited))["status"] == "delivering"


# --- Delivered and returns -----------------------------------------------------------------------


async def test_delivered_everything_accepted(orders, api, supplier, customer) -> None:
    await api.completed(supplier)
    order = ok(await orders.delivering(await orders.create(customer, [box(packs_big=2)])))
    r = await orders.delivered(order, items=[{"item_code": "packs_big", "count": 1}])
    assert_error(r, 422, "VALIDATION_ERROR")
    done = ok(await orders.delivered(order))
    assert done["status"] == "success"
    assert done["delivered_at"] is not None and done["returns"] == []
    assert_error(await orders.delivered(done), 409, "ORDER_INVALID_STATUS")


async def test_delivered_with_returns_validation(orders, api, supplier, customer) -> None:
    await api.completed(supplier)
    order = await orders.create(customer, [box(packs_big=3, liver="0.3")])
    order = ok(await orders.delivering(order))
    cases = [
        ({"items": [{"item_code": "packs_big", "count": 1}]}, ["body", "reason"]),
        ({"reason": "Late"}, ["body", "items"]),
        (
            {"reason": "Late", "items": [{"item_code": "packs_small", "count": 1}]},
            ["body", "items", "0", "item_code"],
        ),
        (
            {"reason": "Late", "items": [{"item_code": "packs_big", "count": 4}]},
            ["body", "items", "0", "count"],
        ),
        (
            {"reason": "Late", "items": [{"item_code": "byproduct_packed.liver", "kg": "0.301"}]},
            ["body", "items", "0", "kg"],
        ),
        (
            {"reason": "Late", "items": [{"item_code": "packs_big", "kg": "1"}]},
            ["body", "items", "0", "kg"],
        ),
    ]
    for body, loc in cases:
        r = await orders.delivered(order, "returned", **body)
        assert_error(r, 422, "VALIDATION_ERROR")
        assert loc in [f["loc"] for f in r.json()["error"]["details"]["fields"]], (body, r.text)
    assert (await orders.get(order))["status"] == "delivering"


async def test_return_review_partly_returned(
    client, session, gm, orders, api, supplier, customer
) -> None:
    first, second = await two_batches(api, supplier)
    order = await orders.create(customer, [box(packs_big=10, liver="0.6")])
    order = ok(await orders.delivering(order))  # big: 7 from first, 3 from second
    order = ok(
        await orders.delivered(
            order,
            "returned",
            reason="  Two packs torn  ",
            items=[
                {"item_code": "packs_big", "count": 5},
                {"item_code": "byproduct_packed.liver", "kg": "0.25"},
            ],
        )
    )
    assert order["status"] == "return_pending"
    assert order["return_reason"] == "Two packs torn"
    returned = {r["item_code"]: r for r in order["returns"]}
    assert returned["packs_big"]["returned_count"] == 5
    assert returned["packs_big"]["delivered_count"] == 10
    assert returned["packs_big"]["to_stock_count"] is None
    assert returned["byproduct_packed.liver"]["returned_kg"] == "0.250"

    # Split must add up; every returned item listed once; units match.
    bad = [
        [{"item_code": "packs_big", "to_stock_count": 3, "to_wasted_count": 1}],
        [{"item_code": "packs_big", "to_stock_count": 3, "to_wasted_count": 2}],
        [
            {"item_code": "packs_big", "to_stock_count": 3, "to_wasted_count": 2},
            {"item_code": "byproduct_packed.liver", "to_stock_count": 1},
        ],
    ]
    for items in bad:
        assert_error(await orders.review(order, items), 422, "VALIDATION_ERROR")

    reviewed = ok(
        await orders.review(
            order,
            [
                {"item_code": "packs_big", "to_stock_count": 3, "to_wasted_count": 2},
                {"item_code": "byproduct_packed.liver", "to_stock_kg": "0.25", "to_wasted_kg": "0"},
            ],
        )
    )
    assert reviewed["status"] == "partly_returned"
    assert reviewed["returns_reviewed_by"]["id"] == str(gm.id)
    split = {r["item_code"]: r for r in reviewed["returns"]}
    assert (split["packs_big"]["to_stock_count"], split["packs_big"]["to_wasted_count"]) == (3, 2)
    assert split["byproduct_packed.liver"]["to_stock_kg"] == "0.250"
    assert split["byproduct_packed.liver"]["to_wasted_kg"] == "0.000"

    items = await stock(client, gm)
    assert items["packs_big"]["count"] == 4 + 3
    assert items["wasted.packs_big"]["count"] == 2
    assert items["byproduct_packed.liver"]["kg"] == "0.450"  # 0.8 - 0.6 + 0.25
    # Back to the batches it came from, newest first: 3 to the second batch (which gave 3), then
    # the 2 wasted continue into the first batch.
    assert await sources(client, gm, "packs_big") == [(second["code"], 7, None)]
    assert await sources(client, gm, "wasted.packs_big") == [(first["code"], 2, None)]
    # Liver: the second batch gave 0.2, the first 0.4 → 0.2 back to the second, 0.05 to the first.
    assert await sources(client, gm, "byproduct_packed.liver") == [
        (first["code"], None, "0.050"),
        (second["code"], None, "0.400"),
    ]
    moves = ok(
        await client.get(
            "/inventory/movements",
            params={"order_id": order["id"], "source": "order_return"},
            headers=auth(gm),
        )
    )["items"]
    assert {m["item_code"] for m in moves} == {
        "packs_big",
        "wasted.packs_big",
        "byproduct_packed.liver",
    }
    log = await session.scalar(select(AuditLog).where(AuditLog.action == "order.returns_reviewed"))
    assert log.details["outcome"] == "partly_returned"
    assert [i["item_code"] for i in log.details["to_wasted"]] == ["packs_big"]
    assert_error(await orders.review(reviewed, []), 409, "ORDER_INVALID_STATUS")


async def test_return_review_fully_returned_and_wasted_byproduct(
    client, gm, orders, api, supplier, customer
) -> None:
    (batch,) = [await api.completed(supplier)]
    order = await orders.create(customer, [box(packs_small=2), box("black", heart="0.4")])
    order = ok(await orders.delivering(order))
    order = ok(
        await orders.delivered(
            order,
            "returned",
            reason="Shop closed",
            items=[
                {"item_code": "packs_small", "count": 2},
                {"item_code": "byproduct_packed.heart", "kg": "0.4"},
            ],
        )
    )
    reviewed = ok(
        await orders.review(
            order,
            [
                {"item_code": "packs_small", "to_stock_count": 2},
                {"item_code": "byproduct_packed.heart", "to_wasted_kg": "0.4"},
            ],
        )
    )
    assert reviewed["status"] == "fully_returned"
    items = await stock(client, gm)
    assert items["packs_small"]["count"] == 5
    assert items["byproduct_packed.heart"]["kg"] == "0.000"
    assert items["wasted.byproduct.heart"]["kg"] == "0.500"  # 0.1 rejected at step 3 + 0.4
    assert await sources(client, gm, "wasted.byproduct.heart") == [(batch["code"], None, "0.500")]


async def test_review_needs_the_permission(client, make_user, orders, api, supplier, customer):
    await api.completed(supplier)
    order = ok(await orders.delivering(await orders.create(customer, [box(packs_big=1)])))
    order = ok(
        await orders.delivered(
            order, "returned", reason="x", items=[{"item_code": "packs_big", "count": 1}]
        )
    )
    sup = await make_user(Role.SUPERVISOR)  # returns Off by default
    r = await Orders(client, sup).review(order, [{"item_code": "packs_big", "to_stock_count": 1}])
    assert_error(r, 403, "MISSING_PERMISSION")


# --- Production guard ----------------------------------------------------------------------------


async def test_reopen_blocked_once_packs_left_in_orders(
    client, gm, orders, api, supplier, customer
) -> None:
    first, second = await two_batches(api, supplier)
    order = await orders.create(customer, [box(packs_big=2)])
    order = ok(await orders.delivering(order))  # taken from the first batch only

    for step in ("standardize", "produced"):
        r = await api.reopen(first, step)
        assert_error(r, 409, "PRODUCTION_STOCK_ALREADY_USED")
        details = r.json()["error"]["details"]
        assert details["orders"] == [order["code"]]
        (item,) = details["items"]
        assert (item["item_code"], item["remaining_count"], item["needed_count"]) == (
            "packs_big",
            5,
            7,
        )
        assert item["orders"] == [order["code"]]
    assert (await api.get(first))["status"] == "completed"
    assert (await stock(client, gm))["packs_big"]["count"] == 12

    # The second batch's packs are untouched: it can be reopened.
    reopened = ok(await api.reopen(second, "standardize"))
    assert reopened["status"] == "in_progress"
    assert (await stock(client, gm))["packs_big"]["count"] == 5

    # Once the packs come back to stock, the first batch can be reopened too.
    order = ok(
        await orders.delivered(
            order, "returned", reason="Wrong shop", items=[{"item_code": "packs_big", "count": 2}]
        )
    )
    ok(await orders.review(order, [{"item_code": "packs_big", "to_stock_count": 2}]))
    assert ok(await api.reopen(first, "standardize"))["status"] == "in_progress"
    assert (await stock(client, gm))["packs_big"]["count"] == 0


async def test_packs_returned_to_wasted_keep_the_batch_locked(
    orders, api, supplier, customer
) -> None:
    batch = await api.completed(supplier)
    order = ok(await orders.delivering(await orders.create(customer, [box(packs_big=1)])))
    order = ok(
        await orders.delivered(
            order, "returned", reason="Torn", items=[{"item_code": "packs_big", "count": 1}]
        )
    )
    ok(await orders.review(order, [{"item_code": "packs_big", "to_wasted_count": 1}]))
    assert_error(await api.reopen(batch, "standardize"), 409, "PRODUCTION_STOCK_ALREADY_USED")


# --- Codes, stats, list --------------------------------------------------------------------------


async def test_codes_are_distinct_under_concurrency(client, gm, customer) -> None:
    async def create() -> str:
        r = await Orders(client, gm).create_raw(customer, [box(packs_big=1)])
        assert r.status_code == 201, r.text
        return r.json()["code"]

    codes = await asyncio.gather(*(create() for _ in range(6)))
    today = business_today()
    assert sorted(codes) == [f"OR-{today:%Y%m%d}-{n:03d}" for n in range(1, 7)]


async def test_stats_and_list_filters(client, gm, orders, api, supplier, customer, make_user):
    await api.completed(supplier)
    other = ok(await client.post("/customers", json={"name": "Bopha Mart"}, headers=auth(gm)), 201)
    driver = await make_user(Role.STAFF)
    created = await orders.create(
        customer, [box(packs_big=1), box("black", packs_small=1)], delivery_date="2026-10-05"
    )
    sent = ok(
        await orders.delivering(
            await orders.create(other, [box(packs_big=1)], driver_id=str(driver.id))
        )
    )
    done = ok(
        await orders.delivered(
            ok(
                await orders.delivering(
                    await orders.create(customer, [box("black", packs_small=1)])
                )
            )
        )
    )
    cancelled = ok(await orders.cancel(await orders.create(other, [box(packs_big=1)])))

    stats = ok(await client.get("/orders/stats", headers=auth(gm)))
    assert stats == {"created": 1, "delivering": 1, "return_pending": 0, "delivered_this_month": 1}

    async def codes(**params) -> list[str]:
        body = ok(await client.get("/orders", params=params, headers=auth(gm)))
        return [o["code"] for o in body["items"]]

    assert set(await codes()) == {o["code"] for o in (created, sent, done, cancelled)}
    assert await codes(status="completed") == [done["code"]]
    assert await codes(status="cancelled") == [cancelled["code"]]
    assert set(await codes(customer_id=other["id"])) == {sent["code"], cancelled["code"]}
    assert await codes(driver_id=str(driver.id)) == [sent["code"]]
    assert await codes(date_from="2026-10-05", date_to="2026-10-05") == [created["code"]]
    assert set(await codes(q="bopha")) == {sent["code"], cancelled["code"]}
    assert await codes(q=created["code"]) == [created["code"]]
    row = ok(await client.get("/orders", params={"q": created["code"]}, headers=auth(gm)))
    (item,) = row["items"]
    assert (item["white_boxes"], item["black_boxes"]) == (1, 1)
    assert item["customer"]["name"] == "Dara Shop"


async def test_available_stock(client, gm, api, supplier) -> None:
    await api.completed(supplier)
    body = ok(await client.get("/orders/available-stock", headers=auth(gm)))
    by_code = {i["item_code"]: i for i in body}
    assert [i["item_code"] for i in body][:2] == ["packs_big", "packs_small"]
    assert (by_code["packs_big"]["unit"], by_code["packs_big"]["count"]) == ("count", 7)
    assert by_code["byproduct_packed.liver"]["kg"] == "0.400"
    assert "wings" not in by_code


async def test_not_found(client, gm) -> None:
    r = await client.get("/orders/00000000-0000-0000-0000-000000000000", headers=auth(gm))
    assert_error(r, 404, "ORDER_NOT_FOUND")


async def test_kg_arithmetic_is_exact(client, gm, orders, api, supplier, customer) -> None:
    await api.completed(supplier)
    order = await orders.create(
        customer, [box(liver="0.1"), box(liver="0.1"), box("black", liver="0.1")]
    )
    total = {i["item_code"]: i for i in order["summary"]["total"]["items"]}
    assert total["byproduct_packed.liver"]["kg"] == "0.300"
    ok(await orders.delivering(order))
    assert (await stock(client, gm))["byproduct_packed.liver"]["kg"] == "0.100"


async def test_audit_log_names_the_order(client, gm, orders, customer) -> None:
    order = await orders.create(customer, [box(packs_big=1)])
    ok(await orders.cancel(order))
    r = await client.get("/audit-logs", params={"entity_type": "order"}, headers=auth(gm))
    entries = ok(r)["items"]
    assert [e["action"] for e in entries] == ["order.cancel", "order.create"]
    assert {(e["entity"]["type"], e["entity"]["name"]) for e in entries} == {
        ("order", order["code"])
    }
