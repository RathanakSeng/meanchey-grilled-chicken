"""Order customers: saved customer or direct order (phone required, location optional), the
snapshot (refreshed while Created, frozen from Delivering on), list filter and search, alerts,
the delivery note and audit; migration 0016 (backfill, CHECKs, downgrade guard)."""

import asyncio
import uuid

import pytest
from alembic import command
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.bot import notify
from app.models import AuditLog, Language, Notification, Role
from tests.conftest import assert_error, auth
from tests.test_migration_step_dates import _alembic, _run
from tests.test_orders import Orders, box
from tests.test_production import Api, ok


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
    body = {"name": "Dara Shop", "phone": "012 888 777", "location": "Phsar Thmei"}
    return ok(await client.post("/customers", json=body, headers=auth(gm)), 201)


def direct_raw(orders: Orders, boxes: list[dict] | None = None, **customer):
    body = {"customer_type": "direct", "boxes": boxes or [box(packs_big=1)], **customer}
    return orders.client.post("/orders", json=body, headers=orders.headers)


async def direct(orders: Orders, **customer) -> dict:
    return ok(await direct_raw(orders, **customer), 201)


async def edit_customer(client, gm, customer: dict, **fields) -> None:
    ok(await client.patch(f"/customers/{customer['id']}", json=fields, headers=auth(gm)))


# --- Create --------------------------------------------------------------------------------------


async def test_saved_customer_snapshot(orders, customer) -> None:
    order = await orders.create(customer, [box(packs_big=1)])
    assert order["customer"] == {
        "type": "saved",
        "id": customer["id"],
        "name": "Dara Shop",
        "phone": "012888777",
        "phone_display": "012 888 777",
        "location": "Phsar Thmei",
        "is_active": True,
    }
    # An explicit type works the same.
    body = {"customer_type": "saved", "customer_id": customer["id"], "boxes": [box(packs_big=1)]}
    r = await orders.client.post("/orders", json=body, headers=orders.headers)
    assert ok(r, 201)["customer"]["type"] == "saved"


async def test_direct_order_phone_required_location_optional(orders) -> None:
    order = await direct(orders, phone="012-345 678", location="  Toul Kork, st 315  ")
    assert order["customer"] == {
        "type": "direct",
        "id": None,
        "name": None,
        "phone": "012345678",
        "phone_display": "012 345 678",
        "location": "Toul Kork, st 315",
        "is_active": None,
    }
    assert (await direct(orders, phone="+855 12 345 678"))["customer"]["location"] is None
    assert (await direct(orders, phone="012345678", location="   "))["customer"]["location"] is None

    for missing in ({}, {"phone": ""}, {"phone": "   "}, {"phone": None}):
        r = await direct_raw(orders, **missing)
        assert_error(r, 422, "VALIDATION_ERROR")
        assert r.json()["error"]["details"]["fields"][0]["loc"] == ["body", "phone"]
    assert_error(await direct_raw(orders, phone="12ab"), 422, "INVALID_PHONE")
    assert_error(await direct_raw(orders, phone="1234"), 422, "INVALID_PHONE")
    r = await direct_raw(orders, phone="012345678", location="x" * 256)
    assert_error(r, 422, "VALIDATION_ERROR")


async def test_customer_fields_must_match_the_type(orders, customer) -> None:
    r = await direct_raw(orders, phone="012345678", customer_id=customer["id"])
    assert_error(r, 422, "VALIDATION_ERROR")
    assert r.json()["error"]["details"]["fields"][0]["loc"] == ["body", "customer_id"]

    r = await orders.create_raw(customer, [box(packs_big=1)], phone="012345678")
    assert_error(r, 422, "VALIDATION_ERROR")
    assert r.json()["error"]["details"]["fields"][0]["loc"] == ["body", "phone"]

    body = {"customer_type": "saved", "boxes": [box(packs_big=1)]}
    r = await orders.client.post("/orders", json=body, headers=orders.headers)
    assert_error(r, 422, "VALIDATION_ERROR")
    assert r.json()["error"]["details"]["fields"][0]["loc"] == ["body", "customer_id"]

    body = {"customer_type": "walk_in", "phone": "012345678", "boxes": [box(packs_big=1)]}
    r = await orders.client.post("/orders", json=body, headers=orders.headers)
    assert_error(r, 422, "VALIDATION_ERROR")


async def test_inactive_customer_refused(client, gm, orders, customer) -> None:
    order = await orders.create(customer, [box(packs_big=1)])
    ok(await client.post(f"/customers/{customer['id']}/deactivate", headers=auth(gm)))
    r = await orders.create_raw(customer, [box(packs_big=1)])
    assert_error(r, 422, "CUSTOMER_INACTIVE")
    # The order that already has them can still be edited (and shows they're inactive).
    order = ok(await orders.patch(order, customer_id=customer["id"], note="Call first"))
    assert order["customer"]["is_active"] is False
    # Switching to them from another order is refused.
    other = await direct(orders, phone="012345678")
    r = await orders.patch(other, customer_type="saved", customer_id=customer["id"])
    assert_error(r, 422, "CUSTOMER_INACTIVE")


# --- Edit ----------------------------------------------------------------------------------------


async def test_switch_type_while_created(session, orders, customer) -> None:
    order = await orders.create(customer, [box(packs_big=1)])
    order = ok(await orders.patch(order, customer_type="direct", phone="097 111 2222"))
    assert order["customer"]["type"] == "direct"
    assert (order["customer"]["id"], order["customer"]["name"]) == (None, None)
    assert order["customer"]["phone"] == "0971112222"
    assert order["customer"]["location"] is None

    # Phone / location alone edit a direct order; the other one is kept.
    order = ok(await orders.patch(order, location="Sen Sok"))
    assert (order["customer"]["phone"], order["customer"]["location"]) == ("0971112222", "Sen Sok")
    order = ok(await orders.patch(order, phone="098 765 432"))
    assert (order["customer"]["phone"], order["customer"]["location"]) == ("098765432", "Sen Sok")
    assert_error(await orders.patch(order, phone=""), 422, "VALIDATION_ERROR")
    assert_error(await orders.patch(order, phone="98"), 422, "INVALID_PHONE")
    order = ok(await orders.patch(order, location=""))
    assert order["customer"]["location"] is None

    # Back to the saved customer (the type defaults to saved).
    order = ok(await orders.patch(order, customer_id=customer["id"]))
    assert order["customer"]["type"] == "saved"
    assert order["customer"]["name"] == "Dara Shop"
    # Phone / location belong to direct orders only.
    r = await orders.patch(order, phone="012345678")
    assert_error(r, 422, "VALIDATION_ERROR")

    entries = (
        await session.scalars(
            select(AuditLog)
            .where(AuditLog.action == "order.update", AuditLog.entity_id == uuid.UUID(order["id"]))
            .order_by(AuditLog.created_at, AuditLog.id)
        )
    ).all()
    first = entries[0].details["changes"]
    assert first["customer_type"] == {"from": "saved", "to": "direct"}
    assert first["customer"] == {"from": "Dara Shop", "to": None}
    assert first["customer_phone"] == {"from": "012 888 777", "to": "097 111 2222"}
    assert first["customer_location"] == {"from": "Phsar Thmei", "to": None}
    assert entries[1].details["changes"] == {"customer_location": {"from": None, "to": "Sen Sok"}}

    created = await session.scalar(select(AuditLog).where(AuditLog.action == "order.create"))
    assert created is not None
    assert created.details["customer_type"] == "saved"
    assert created.details["customer_phone"] == "012 888 777"


async def test_snapshot_refreshed_while_created_frozen_after_delivering(
    client, gm, api, supplier, orders, customer
) -> None:
    await api.completed(supplier)
    order = await orders.create(customer, [box(packs_big=1)])

    # The customer changes: the order keeps its snapshot until it's saved again.
    await edit_customer(client, gm, customer, name="Dara Shop 2", location="Olympic")
    assert (await orders.get(order))["customer"]["name"] == "Dara Shop"
    order = ok(await orders.patch(order, note="Call first"))
    assert (order["customer"]["name"], order["customer"]["location"]) == ("Dara Shop 2", "Olympic")

    # Delivering takes the latest details once more...
    await edit_customer(client, gm, customer, name="Dara Shop 3", phone="011 222 333")
    order = ok(await orders.delivering(order))
    assert order["customer"]["name"] == "Dara Shop 3"
    assert order["customer"]["phone_display"] == "011 222 333"

    # ...and from then on they're frozen.
    await edit_customer(client, gm, customer, name="Someone Else", phone="", location="")
    order = await orders.get(order)
    assert order["customer"]["name"] == "Dara Shop 3"
    assert order["customer"]["phone"] == "011222333"
    assert order["customer"]["location"] == "Olympic"
    order = ok(await orders.delivered(order))
    assert order["customer"]["name"] == "Dara Shop 3"
    page = ok(await client.get("/orders", params={"q": "Dara Shop 3"}, headers=auth(gm)))
    assert [o["code"] for o in page["items"]] == [order["code"]]


# --- List ----------------------------------------------------------------------------------------


async def test_filter_and_search(client, gm, orders, customer) -> None:
    saved = await orders.create(customer, [box(packs_big=1)])
    walk_in = await direct(orders, phone="012 345 678", location="Toul Kork")
    other = await direct(orders, phone="+855 97 000 111")

    async def codes(**params) -> list[str]:
        page = ok(await client.get("/orders", params=params, headers=auth(gm)))
        return sorted(o["code"] for o in page["items"])

    assert await codes(customer_type="direct") == sorted([walk_in["code"], other["code"]])
    assert await codes(customer_type="saved") == [saved["code"]]
    assert await codes(customer_id=customer["id"]) == [saved["code"]]
    assert await codes(customer_type="direct", customer_id=customer["id"]) == []
    assert await codes(q="012 345") == [walk_in["code"]]  # phone digits
    assert await codes(q="012-345-678") == [walk_in["code"]]
    assert await codes(q="toul kork") == [walk_in["code"]]  # location
    assert await codes(q="dara") == [saved["code"]]  # name
    assert await codes(q="888 777") == [saved["code"]]  # saved customer's phone
    assert await codes(q="97 000") == [other["code"]]
    r = await client.get("/orders", params={"customer_type": "other"}, headers=auth(gm))
    assert_error(r, 422, "VALIDATION_ERROR")

    page = ok(await client.get("/orders", params={"customer_type": "direct"}, headers=auth(gm)))
    item = next(o for o in page["items"] if o["code"] == walk_in["code"])
    assert item["customer"]["type"] == "direct"
    assert item["customer"]["phone_display"] == "012 345 678"
    assert item["customer"]["location"] == "Toul Kork"


async def test_customer_options_include_location(client, gm, customer) -> None:
    options = ok(await client.get("/orders/customer-options", headers=auth(gm)))
    assert options == [
        {
            "id": customer["id"],
            "name": "Dara Shop",
            "phone_display": "012 888 777",
            "location": "Phsar Thmei",
        }
    ]


# --- Alerts and the delivery note ----------------------------------------------------------------


async def test_direct_order_alerts(session, gm, api, supplier, orders) -> None:
    await api.completed(supplier)
    order = await direct(orders, phone="012 345 678", location="Toul Kork")
    ok(await orders.delivering(order))
    row = await session.scalar(
        select(Notification).where(
            Notification.type == "order.delivering", Notification.user_id == gm.id
        )
    )
    assert row is not None
    assert row.payload["customer"] is None
    assert row.payload["customer_type"] == "direct"
    assert row.payload["customer_phone"] == "012 345 678"
    km, _ = notify.message_for(row, Language.KM)
    assert "សម្រាប់ ការបញ្ជាទិញផ្ទាល់ · 012 345 678 កំពុងដឹកជញ្ជូន" in km
    en, _ = notify.message_for(row, Language.EN)
    assert "for Direct order · 012 345 678 is out for delivery" in en


async def test_direct_order_delivery_note(client, gm, orders, html_documents) -> None:
    order = await direct(orders, phone="012 345 678", location="Toul Kork")
    r = await client.get(f"/orders/{order['id']}/document.pdf", headers=auth(gm))
    assert r.status_code == 200, r.text
    text = r.text
    for expected in ("ការបញ្ជាទិញផ្ទាល់", "Direct order", "012 345 678", "Toul Kork"):
        assert expected in text, expected
    assert "None" not in text


# --- Migration 0016 ------------------------------------------------------------------------------


def test_customer_snapshot_migration() -> None:
    customer_id, order_id = uuid.uuid4(), uuid.uuid4()
    _alembic(command.downgrade, "0015")
    try:
        asyncio.run(
            _run(
                "INSERT INTO customers (id, name, phone, location) "
                "VALUES (:customer, 'Sokha Mart', '012555444', 'Kandal')",
                "INSERT INTO orders (id, code, customer_id, delivery_date) "
                "VALUES (:order, 'OR-20261001-001', :customer, '2026-10-01')",
                customer=customer_id,
                order=order_id,
            )
        )
    finally:
        _alembic(command.upgrade, "head")
    rows = asyncio.run(
        _run(
            "SELECT customer_type, customer_id, customer_name, customer_phone, customer_location "
            "FROM orders WHERE id = :order",
            order=order_id,
        )
    )
    assert rows == [("saved", customer_id, "Sokha Mart", "012555444", "Kandal")]

    # saved needs a customer; direct needs a phone and no customer.
    for values in (
        "'saved', NULL, '012555444'",
        "'direct', NULL, NULL",
        f"'direct', '{customer_id}', '012555444'",
        "'walk_in', NULL, '012555444'",
    ):
        with pytest.raises(IntegrityError):
            asyncio.run(
                _run(
                    "INSERT INTO orders (id, code, delivery_date, customer_type, customer_id, "
                    f"customer_phone) VALUES (gen_random_uuid(), 'OR-X', '2026-10-01', {values})"
                )
            )

    # A direct order can't be downgraded (it has no customer to point back to).
    asyncio.run(
        _run(
            "INSERT INTO orders (id, code, delivery_date, customer_type, customer_phone) "
            "VALUES (gen_random_uuid(), 'OR-20261001-002', '2026-10-01', 'direct', '012345678')"
        )
    )
    with pytest.raises(RuntimeError, match="direct order"):
        _alembic(command.downgrade, "0015")
    columns = asyncio.run(
        _run(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'orders' AND column_name = 'customer_type'"
        )
    )
    assert columns == [("customer_type",)]
