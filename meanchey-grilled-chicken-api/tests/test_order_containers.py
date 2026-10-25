"""Returnable containers: defaults per container type and overrides, the containers recorded at
Delivered (every returnable box, a reason when not returned), marking them returned later
(`orders.containers`), cancelled orders, the list filter and counts, the delivery note section,
the order_containers feature and migration 0028 (backfill)."""

import asyncio
import uuid

import pytest
from alembic import command
from sqlalchemy import select

from app.models import AuditLog, Role
from app.models.order import BOX_COLORS, BOX_RETURNABLE
from app.permissions import registry
from tests.conftest import assert_error, auth
from tests.test_documents import html
from tests.test_migration_step_dates import _alembic, _run
from tests.test_orders import Orders, all_returned, box
from tests.test_production import Api, ok

CODE = "orders.containers"


@pytest.fixture
async def gm(make_user):
    return await make_user(Role.GENERAL_MANAGER)


@pytest.fixture
def api(client, gm) -> Api:
    return Api(client, gm)


@pytest.fixture
def orders(client, gm) -> Orders:
    return Orders(client, gm)


@pytest.fixture
async def supplier(client, gm) -> dict:
    return ok(await client.post("/suppliers", json={"name": "Sokha Farm"}, headers=auth(gm)), 201)


@pytest.fixture
async def customer(client, gm) -> dict:
    return ok(await client.post("/customers", json={"name": "Dara Shop"}, headers=auth(gm)), 201)


def boxes_of(order: dict) -> list[tuple[str, bool, str | None]]:
    return [(b["color"], b["returnable"], b["container_status"]) for b in order["boxes"]]


async def delivering(api: Api, supplier: dict, orders: Orders, customer: dict, boxes) -> dict:
    await api.completed(supplier)
    return ok(await orders.delivering(await orders.create(customer, boxes)))


def returnable_ids(order: dict) -> list[str]:
    return [b["id"] for b in order["boxes"] if b["returnable"]]


# --- Defaults and the form -----------------------------------------------------------------------


def test_every_container_type_declares_a_default() -> None:
    assert set(BOX_RETURNABLE) == set(BOX_COLORS)
    assert BOX_RETURNABLE == {
        "white": True,
        "black": True,
        "plastic_bag": False,
        "delivery_bag": False,
    }


async def test_defaults_per_type_and_explicit_override(orders, customer) -> None:
    order = await orders.create(
        customer,
        [
            box("white", packs_big=1),
            box("black", packs_big=1),
            box("plastic_bag", packs_small=1),
            box("delivery_bag", packs_small=1),
        ],
    )
    assert boxes_of(order) == [
        ("white", True, "pending"),
        ("black", True, "pending"),
        ("plastic_bag", False, None),
        ("delivery_bag", False, None),
    ]
    assert order["containers"] == {
        "total_returnable": 2,
        "returned": 0,
        "not_returned": 0,
        "pending": 2,
    }
    overridden = await orders.create(
        customer,
        [
            {**box("white", packs_big=1), "returnable": False},
            {**box("plastic_bag", packs_big=1), "returnable": True},
        ],
    )
    assert boxes_of(overridden) == [("white", False, None), ("plastic_bag", True, "pending")]
    assert overridden["containers"]["total_returnable"] == 1


async def test_edit_type_change_applies_the_new_default(orders, customer) -> None:
    order = await orders.create(customer, [box("white", packs_big=1), box("black", packs_big=1)])
    # The first box becomes a plastic bag (no returnable sent → its default, not returnable); the
    # second keeps its type but is set explicitly.
    order = ok(
        await orders.patch(
            order,
            boxes=[
                box("plastic_bag", packs_big=1),
                {**box("black", packs_big=1), "returnable": False},
            ],
        )
    )
    assert boxes_of(order) == [("plastic_bag", False, None), ("black", False, None)]
    assert order["containers"]["total_returnable"] == 0
    order = ok(await orders.patch(order, boxes=[box("black", packs_big=1)]))
    assert boxes_of(order) == [("black", True, "pending")]


# --- Delivered -----------------------------------------------------------------------------------


@pytest.mark.parametrize("outcome", ["accepted", "returned"])
async def test_delivered_requires_every_returnable_box(
    api, supplier, orders, customer, outcome
) -> None:
    order = await delivering(
        api,
        supplier,
        orders,
        customer,
        [box("white", packs_big=1), box("plastic_bag", packs_big=1), box("black", packs_big=1)],
    )
    white, bag, black = (b["id"] for b in order["boxes"])
    extra = (
        {"reason": "Crushed", "items": [{"item_code": "packs_big", "count": 1}]}
        if outcome == "returned"
        else {}
    )

    # Missing: none, then one box.
    r = await orders.delivered(order, outcome, containers=[], **extra)
    assert_error(r, 422, "ORDER_CONTAINERS_REQUIRED")
    assert set(r.json()["error"]["details"]["box_ids"]) == {white, black}
    r = await orders.delivered(
        order, outcome, containers=[{"box_id": white, "returned": True}], **extra
    )
    assert_error(r, 422, "ORDER_CONTAINERS_REQUIRED")
    assert r.json()["error"]["details"]["box_ids"] == [black]
    # Extra: a box that isn't returnable, an unknown box, a box twice.
    for wrong in (bag, str(uuid.uuid4()), white):
        containers = [
            {"box_id": white, "returned": True},
            {"box_id": black, "returned": True},
            {"box_id": wrong, "returned": True},
        ]
        r = await orders.delivered(order, outcome, containers=containers, **extra)
        assert_error(r, 422, "ORDER_CONTAINERS_REQUIRED")
        assert r.json()["error"]["details"]["extra_box_ids"] == [wrong]
    # Not returned without a reason.
    containers = [{"box_id": white, "returned": True}, {"box_id": black, "returned": False}]
    r = await orders.delivered(order, outcome, containers=containers, **extra)
    assert_error(r, 422, "VALIDATION_ERROR")
    assert r.json()["error"]["details"]["fields"][0]["loc"] == ["body", "containers", "1", "reason"]
    containers[1]["reason"] = "   "
    assert_error(
        await orders.delivered(order, outcome, containers=containers, **extra),
        422,
        "VALIDATION_ERROR",
    )
    assert (await orders.get(order))["status"] == "delivering"

    containers[1]["reason"] = " Customer keeps it until tomorrow "
    done = ok(await orders.delivered(order, outcome, containers=containers, **extra))
    assert done["status"] == ("success" if outcome == "accepted" else "return_pending")
    assert boxes_of(done) == [
        ("white", True, "returned"),
        ("plastic_bag", False, None),
        ("black", True, "not_returned"),
    ]
    black_box = done["boxes"][2]
    assert black_box["container_reason"] == "Customer keeps it until tomorrow"
    assert black_box["container_recorded_by"]["id"] == done["delivered_by"]["id"]
    assert black_box["container_recorded_at"] is not None
    assert done["boxes"][0]["container_reason"] is None
    assert done["containers"] == {
        "total_returnable": 2,
        "returned": 1,
        "not_returned": 1,
        "pending": 0,
    }


async def test_orders_without_returnable_boxes_need_no_containers(
    api, supplier, orders, customer
) -> None:
    order = await delivering(api, supplier, orders, customer, [box("plastic_bag", packs_big=1)])
    done = ok(await orders.delivered(order, containers=[]))
    assert done["status"] == "success"
    assert done["containers"] == {
        "total_returnable": 0,
        "returned": 0,
        "not_returned": 0,
        "pending": 0,
    }


async def test_containers_audit(session, api, supplier, orders, customer) -> None:
    order = await delivering(
        api, supplier, orders, customer, [box("white", packs_big=1), box("black", packs_big=1)]
    )
    white, black = returnable_ids(order)
    containers = [
        {"box_id": black, "returned": False, "reason": "Lost"},
        {"box_id": white, "returned": True, "reason": "ignored when returned"},
    ]
    ok(await orders.delivered(order, containers=containers))
    log = await session.scalar(
        select(AuditLog).where(AuditLog.action == "order.containers_recorded")
    )
    assert log.entity_type == "order" and log.details["code"] == order["code"]
    assert log.details["boxes"] == [
        {"box": 1, "color": "white", "returned": True, "reason": None},
        {"box": 2, "color": "black", "returned": False, "reason": "Lost"},
    ]


# --- Returned later ------------------------------------------------------------------------------


def returned_later(client, user, order: dict, box_id: str):
    return client.post(
        f"/orders/{order['id']}/boxes/{box_id}/container-returned", headers=auth(user)
    )


async def test_mark_returned_later(client, session, gm, api, supplier, orders, customer) -> None:
    order = await delivering(
        api, supplier, orders, customer, [box("white", packs_big=1), box("black", packs_big=1)]
    )
    white, black = returnable_ids(order)
    # Before Delivered: still pending.
    assert_error(await returned_later(client, gm, order, white), 409, "ORDER_CONTAINER_STATE")
    containers = [
        {"box_id": white, "returned": True},
        {"box_id": black, "returned": False, "reason": "Not ready"},
    ]
    done = ok(await orders.delivered(order, containers=containers))
    # Already returned.
    r = await returned_later(client, gm, done, white)
    assert_error(r, 409, "ORDER_CONTAINER_STATE")
    assert r.json()["error"]["details"]["container_status"] == "returned"
    # Unknown box.
    assert_error(await returned_later(client, gm, done, str(uuid.uuid4())), 404, "ORDER_NOT_FOUND")

    later = ok(await returned_later(client, gm, done, black))
    black_box = later["boxes"][1]
    assert black_box["container_status"] == "returned"
    assert black_box["container_reason"] == "Not ready"  # kept
    assert black_box["container_returned_later_by"]["id"] == str(gm.id)
    assert black_box["container_returned_later_at"] is not None
    assert later["containers"]["not_returned"] == 0 and later["containers"]["returned"] == 2
    # Like printing, it doesn't change the version.
    assert later["version"] == done["version"]
    # Twice → refused.
    assert_error(await returned_later(client, gm, later, black), 409, "ORDER_CONTAINER_STATE")

    log = await session.scalar(
        select(AuditLog).where(AuditLog.action == "order.container_returned")
    )
    assert log.details == {"code": order["code"], "box": 2, "color": "black", "reason": "Not ready"}
    assert log.actor_id == gm.id


async def test_returned_later_after_the_return_review(api, supplier, orders, customer, client, gm):
    order = await delivering(api, supplier, orders, customer, [box("white", packs_big=2)])
    (white,) = returnable_ids(order)
    order = ok(
        await orders.delivered(
            order,
            "returned",
            reason="Crushed",
            items=[{"item_code": "packs_big", "count": 1}],
            containers=[{"box_id": white, "returned": False, "reason": "Kept by the shop"}],
        )
    )
    order = ok(await orders.review(order, [{"item_code": "packs_big", "to_stock_count": 1}]))
    assert order["status"] == "partly_returned"
    later = ok(await returned_later(client, gm, order, white))
    assert later["boxes"][0]["container_status"] == "returned"


async def test_returned_later_needs_the_permission(
    client, gm, make_user, api, supplier, orders, customer
) -> None:
    order = await delivering(api, supplier, orders, customer, [box("white", packs_big=1)])
    (white,) = returnable_ids(order)
    done = ok(
        await orders.delivered(
            order, containers=[{"box_id": white, "returned": False, "reason": "Later"}]
        )
    )
    sup = await make_user(Role.SUPERVISOR)  # Orders Record, containers Off
    staff = await make_user(Role.STAFF)
    for user in (sup, staff):
        assert_error(await returned_later(client, user, done, white), 403, "MISSING_PERMISSION")
    # Given by the GM: the staff member can now mark it.
    ok(
        await client.put(
            f"/users/{staff.id}/features/order_containers",
            json={"level": "full"},
            headers=auth(gm),
        )
    )
    ok(await returned_later(client, staff, done, white))


# --- Cancelled -----------------------------------------------------------------------------------


async def test_cancelled_orders_have_no_containers(client, gm, orders, customer) -> None:
    order = await orders.create(customer, [box("white", packs_big=1)])
    cancelled = ok(await orders.cancel(order))
    assert cancelled["containers"] is None
    assert boxes_of(cancelled) == [("white", True, None)]
    assert_error(
        await returned_later(client, gm, cancelled, cancelled["boxes"][0]["id"]),
        409,
        "ORDER_CONTAINER_STATE",
    )


# --- List ----------------------------------------------------------------------------------------


async def test_list_filter_and_counts(client, gm, api, supplier, orders, customer) -> None:
    await api.completed(supplier)
    two = [box("white", packs_big=1), box("black", packs_big=1)]
    outstanding = ok(await orders.delivering(await orders.create(customer, two)))
    containers = [
        {"box_id": i, "returned": False, "reason": "Later"} for i in returnable_ids(outstanding)
    ]
    outstanding = ok(await orders.delivered(outstanding, containers=containers))
    all_back = ok(await orders.delivering(await orders.create(customer, two)))
    all_back = ok(await orders.delivered(all_back, containers=all_returned(all_back)))
    created = await orders.create(customer, two)

    body = ok(await client.get("/orders", headers=auth(gm)))
    counts = {i["code"]: i["containers_outstanding"] for i in body["items"]}
    assert counts == {outstanding["code"]: 2, all_back["code"]: 0, created["code"]: 0}

    body = ok(await client.get("/orders?containers=outstanding", headers=auth(gm)))
    assert [i["code"] for i in body["items"]] == [outstanding["code"]] and body["total"] == 1

    ok(await returned_later(client, gm, outstanding, outstanding["boxes"][0]["id"]))
    body = ok(await client.get("/orders?containers=outstanding", headers=auth(gm)))
    assert body["items"][0]["containers_outstanding"] == 1
    ok(await returned_later(client, gm, outstanding, outstanding["boxes"][1]["id"]))
    body = ok(await client.get("/orders?containers=outstanding", headers=auth(gm)))
    assert body["total"] == 0

    r = await client.get("/orders?containers=all", headers=auth(gm))
    assert_error(r, 422, "VALIDATION_ERROR")


# --- Delivery note -------------------------------------------------------------------------------


async def test_note_lists_the_containers_to_return(
    client, gm, orders, customer, html_documents
) -> None:
    order = await orders.create(
        customer,
        [
            box("white", packs_big=1),
            box("plastic_bag", packs_big=1),
            {**box("black", packs_big=1), "returnable": False},
            {**box("delivery_bag", packs_big=1), "returnable": True},
        ],
    )
    text = await html(client, gm, order)
    assert 'class="containers"' in text
    assert "ប្រអប់ត្រូវយកមកវិញ" in text and "Containers to return" in text
    section = text[text.index('class="containers"') : text.index('class="signatures"')]
    assert section.count('class="tick"') == 2
    assert "ប្រអប់ទី 1 · ប្រអប់ស / Box 1 · White box" in section
    assert "ប្រអប់ទី 4 · កាបូបដឹកជញ្ជូន / Box 4 · Delivery bag" in section
    assert "Box 2" not in section and "Box 3" not in section
    assert section.count("បានយកមកវិញ / Returned") == 2
    assert section.count("មូលហេតុ / Reason:") == 2

    bags = await orders.create(customer, [box("plastic_bag", packs_big=1)])
    assert 'class="containers"' not in await html(client, gm, bags)
    cancelled = ok(await orders.cancel(await orders.create(customer, [box("white", packs_big=1)])))
    assert 'class="containers"' not in await html(client, gm, cancelled)


# --- Access --------------------------------------------------------------------------------------


def test_feature_and_defaults() -> None:
    feature = registry.FEATURES_BY_CODE["order_containers"]
    assert feature.menu == "workstation"
    assert feature.level_map == {"off": frozenset(), "full": {CODE}}
    assert set(feature.applies_to) == {Role.GENERAL_MANAGER, Role.SUPERVISOR, Role.STAFF}
    defaults = registry.DEFAULT_PERMISSIONS
    assert CODE in defaults[Role.GENERAL_MANAGER]
    assert CODE not in defaults[Role.SUPERVISOR]
    assert CODE not in defaults[Role.STAFF]


async def test_supervisor_gives_staff_only_while_holding_it(client, gm, make_user) -> None:
    sup = await make_user(Role.SUPERVISOR, perms=["users.view", "users.manage_access"])
    staff = await make_user(Role.STAFF)
    url = f"/users/{staff.id}/features/order_containers"
    r = await client.put(url, json={"level": "full"}, headers=auth(sup))
    assert_error(r, 403, "PERMISSION_NOT_HELD")
    ok(
        await client.put(
            f"/users/{sup.id}/features/order_containers",
            json={"level": "full"},
            headers=auth(gm),
        )
    )
    ok(await client.put(url, json={"level": "full"}, headers=auth(sup)))


# --- Migration 0028 ------------------------------------------------------------------------------


def test_migration_backfill() -> None:
    ids = {name: uuid.uuid4() for name in ("created", "delivering", "success", "cancelled")}
    _alembic(command.downgrade, "0027")
    try:
        statements = [
            "INSERT INTO customers (id, name) VALUES (:customer, 'Backfill Shop')",
        ]
        for n, (status, order_id) in enumerate(ids.items(), start=1):
            statements.append(
                "INSERT INTO orders (id, code, customer_type, customer_id, customer_name, "
                f"delivery_date, status) VALUES ('{order_id}', 'OR-20000101-{n:03d}', 'saved', "
                f":customer, 'Backfill Shop', '2000-01-01', '{status}')"
            )
            for position, color in enumerate(("white", "black", "plastic_bag"), start=1):
                statements.append(
                    "INSERT INTO order_boxes (id, order_id, color, position) VALUES "
                    f"('{uuid.uuid4()}', '{order_id}', '{color}', {position})"
                )
        asyncio.run(_run(*statements, customer=uuid.uuid4()))
    finally:
        _alembic(command.upgrade, "head")
    try:
        rows = asyncio.run(
            _run(
                "SELECT o.status, b.color, b.returnable, b.container_status FROM order_boxes b "
                "JOIN orders o ON o.id = b.order_id WHERE o.code LIKE 'OR-20000101-%' "
                "ORDER BY o.code, b.position"
            )
        )
        assert [tuple(r) for r in rows] == [
            ("created", "white", True, "pending"),
            ("created", "black", True, "pending"),
            ("created", "plastic_bag", False, None),
            ("delivering", "white", True, "pending"),
            ("delivering", "black", True, "pending"),
            ("delivering", "plastic_bag", False, None),
            ("success", "white", False, None),
            ("success", "black", False, None),
            ("success", "plastic_bag", False, None),
            ("cancelled", "white", False, None),
            ("cancelled", "black", False, None),
            ("cancelled", "plastic_bag", False, None),
        ]
    finally:
        asyncio.run(
            _run(
                "DELETE FROM orders WHERE code LIKE 'OR-20000101-%'",
                "DELETE FROM customers WHERE name = 'Backfill Shop'",
            )
        )
