"""Order alerts: recipients (holders of orders.review_returns), one per status change, the bell,
and the Telegram texts and buttons (escaped)."""

import pytest
from sqlalchemy import select, update

from app.bot import notify
from app.bot.runtime import TelegramRuntime
from app.bot.setup import create_bot, create_dispatcher
from app.config import get_settings
from app.main import app
from app.models import Language, Notification, Role, User
from tests.conftest import auth
from tests.telegram_fakes import RecordingSession
from tests.test_orders import Orders, box
from tests.test_production import Api, ok

MINI_APP = "https://meanchey.example.com"


@pytest.fixture
async def gm(make_user):
    return await make_user(Role.GENERAL_MANAGER, telegram_user_id=1001)


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
    body = {"name": "Dara <Shop> & Co"}
    return ok(await client.post("/customers", json=body, headers=auth(gm)), 201)


async def _rows(session, **where) -> list[Notification]:
    """Order alerts only (the batches set up for stock send production alerts too)."""
    stmt = (
        select(Notification)
        .where(Notification.type.like("order.%"))
        .order_by(Notification.created_at, Notification.id)
        .execution_options(populate_existing=True)
    )
    for key, value in where.items():
        stmt = stmt.where(getattr(Notification, key) == value)
    return list(await session.scalars(stmt))


async def _set_level(client, gm, user, feature: str, level: str) -> None:
    r = await client.put(
        f"/users/{user.id}/features/{feature}", json={"level": level}, headers=auth(gm)
    )
    assert r.status_code == 200, r.text


async def _returned_order(orders: Orders, customer: dict) -> dict:
    order = await orders.create(customer, [box("white", packs_big=3), box("black", liver="0.3")])
    order = ok(await orders.delivering(order))
    return ok(
        await orders.delivered(
            order,
            "returned",
            reason="Box <wet>",
            items=[
                {"item_code": "packs_big", "count": 2},
                {"item_code": "byproduct_packed.liver", "kg": "0.1"},
            ],
        )
    )


async def test_recipients_and_one_alert_per_status(
    client, session, gm, superadmin, make_user, api, supplier, orders, customer
) -> None:
    reviewer = await make_user(Role.SUPERVISOR)
    await _set_level(client, gm, reviewer, "order_returns", "full")
    plain = await make_user(Role.SUPERVISOR)  # Orders Record, returns Off
    staff = await make_user(Role.STAFF, perms=["orders.view", "orders.create"])
    gone = await make_user(Role.SUPERVISOR)
    await _set_level(client, gm, gone, "order_returns", "full")
    await session.execute(update(User).where(User.id == gone.id).values(is_active=False))
    await session.commit()
    await api.completed(supplier)

    # Created: no alert. Staff starts the delivery: the reviewers are told.
    order = await orders.create(customer, [box("white", packs_big=1), box("black", packs_small=1)])
    assert await _rows(session) == []
    ok(await Orders(client, staff).delivering(order))
    rows = await _rows(session, type="order.delivering")
    assert {r.user_id for r in rows} == {gm.id, superadmin.id, reviewer.id}
    assert not {plain.id, staff.id, gone.id} & {r.user_id for r in rows}
    row = rows[0]
    assert (row.entity_type, str(row.entity_id)) == ("order", order["id"])
    assert row.payload == {
        "code": order["code"],
        "customer": "Dara <Shop> & Co",
        "actor_id": str(staff.id),
        "white": 1,
        "black": 1,
        "repeat": False,
    }
    assert {r.telegram_status for r in rows} == {"bot_off"}

    order = await orders.get(order)
    ok(await orders.delivered(order))
    (delivered,) = await _rows(session, type="order.delivered", user_id=gm.id)
    assert delivered.payload["code"] == order["code"]
    assert len(await _rows(session)) == 6


async def test_return_and_review_alerts(session, gm, api, supplier, orders, customer) -> None:
    await api.completed(supplier)
    order = await _returned_order(orders, customer)
    (pending,) = await _rows(session, type="order.return_pending", user_id=gm.id)
    assert pending.payload["reason"] == "Box <wet>"
    assert pending.payload["returned"] == [
        {
            "item_code": "packs_big",
            "name_en": "4-Piece Packs",
            "name_km": "កញ្ចប់ ៤ ដុំ",
            "count": 2,
            "kg": None,
        },
        {
            "item_code": "byproduct_packed.liver",
            "name_en": "Liver (packed)",
            "name_km": pending.payload["returned"][1]["name_km"],
            "count": None,
            "kg": "0.100",
        },
    ]
    ok(
        await orders.review(
            order,
            [
                {"item_code": "packs_big", "to_stock_count": 1, "to_wasted_count": 1},
                {"item_code": "byproduct_packed.liver", "to_stock_kg": "0.1"},
            ],
        )
    )
    (reviewed,) = await _rows(session, type="order.returns_reviewed", user_id=gm.id)
    assert reviewed.payload["outcome"] == "partly_returned"
    assert [i["item_code"] for i in reviewed.payload["to_stock"]] == [
        "packs_big",
        "byproduct_packed.liver",
    ]
    assert [(i["item_code"], i["count"]) for i in reviewed.payload["to_wasted"]] == [
        ("packs_big", 1)
    ]


async def test_failed_delivering_creates_no_alert(session, orders, customer) -> None:
    order = await orders.create(customer, [box(packs_big=1)])  # nothing in stock
    r = await orders.delivering(order)
    assert r.status_code == 409
    assert await _rows(session) == []


async def test_bell_lists_order_alerts(client, gm, api, supplier, orders, customer) -> None:
    await api.completed(supplier)
    ok(await orders.delivering(await orders.create(customer, [box(packs_big=1)])))
    body = ok(await client.get("/notifications", headers=auth(gm)))
    types = [n["type"] for n in body["items"]]
    assert "order.delivering" in types
    item = next(n for n in body["items"] if n["type"] == "order.delivering")
    assert item["entity_type"] == "order"
    assert item["actor"]["id"] == str(gm.id)
    assert "actor_id" not in item["payload"]


# --- Telegram ------------------------------------------------------------------------------------


@pytest.fixture
def tg() -> RecordingSession:
    return RecordingSession()


@pytest.fixture
def webhook_bot(tg, monkeypatch):
    monkeypatch.setattr(get_settings(), "bot_mode", "webhook")
    monkeypatch.setattr(get_settings(), "mini_app_url", MINI_APP)
    app.state.telegram = TelegramRuntime(
        bot=create_bot(session=tg), dp=create_dispatcher(), secret="s"
    )
    yield tg
    app.state.telegram = None


async def test_telegram_texts_and_open_order_button(
    session, gm, api, supplier, orders, customer, webhook_bot
) -> None:
    await api.completed(supplier)
    order = await _returned_order(orders, customer)
    ok(
        await orders.review(
            order,
            [
                {"item_code": "packs_big", "to_stock_count": 2},
                {"item_code": "byproduct_packed.liver", "to_wasted_kg": "0.1"},
            ],
        )
    )
    sent = webhook_bot.calls("SendMessage")
    to_gm = [m for m in sent if m.chat_id == gm.telegram_user_id and order["code"] in m.text]
    texts = [m.text for m in to_gm]
    code = order["code"]
    customer_html = "Dara &lt;Shop&gt; &amp; Co"
    # Khmer is the default language.
    assert len(texts) == 3
    assert texts[0] == (f"🚚 <b>{code}</b> សម្រាប់ {customer_html} កំពុងដឹកជញ្ជូន — ប្រអប់ស 1 / ប្រអប់ខ្មៅ 1។")
    assert texts[1].startswith(f"↩️ <b>{code}</b>៖ {customer_html} បានប្រគល់ទំនិញមកវិញ — កញ្ចប់ ៤ ដុំ 2, ")
    assert "0.100 គ.ក" in texts[1] and "“Box &lt;wet&gt;”" in texts[1]
    # 2 of 3 packs and 0.1 of 0.3 kg came back: partly returned.
    assert texts[2].startswith(f"📦 <b>{code}</b>៖ បានពិនិត្យទំនិញប្រគល់មកវិញ — ប្រគល់មកវិញខ្លះ")
    button = to_gm[0].reply_markup.inline_keyboard[0][0]
    assert button.web_app.url == f"{MINI_APP}/workstation/orders/{order['id']}"
    rows = await _rows(session, user_id=gm.id)
    assert {r.telegram_status for r in rows} == {"sent"}


def test_english_texts() -> None:
    def row(type_: str, **payload) -> Notification:
        return Notification(
            type=type_,
            entity_type="order",
            entity_id="00000000-0000-0000-0000-000000000001",
            payload={"code": "OR-20261003-001", "customer": "Dara <Shop>", **payload},
        )

    liver = {"name_en": "Liver (packed)", "name_km": "x", "count": None, "kg": "0.250"}
    packs = {"name_en": "4-Piece Packs", "name_km": "x", "count": 3, "kg": None}
    cases = [
        (
            row("order.delivering", white=2, black=1),
            "🚚 <b>OR-20261003-001</b> for Dara &lt;Shop&gt; is out for delivery — 2 white / "
            "1 black boxes.",
        ),
        (
            row("order.delivered"),
            "✅ <b>OR-20261003-001</b>: delivered to Dara &lt;Shop&gt;, everything accepted.",
        ),
        (
            row("order.return_pending", returned=[packs, liver], reason="Late & cold"),
            "↩️ <b>OR-20261003-001</b>: Dara &lt;Shop&gt; returned items — 3 × 4-Piece Packs, "
            "0.250 kg Liver (packed). Reason: “Late &amp; cold”. Review the return.",
        ),
        (
            row(
                "order.returns_reviewed", outcome="partly_returned", to_stock=[packs], to_wasted=[]
            ),
            "📦 <b>OR-20261003-001</b>: return reviewed — partly returned (3 × 4-Piece Packs to "
            "stock, nothing wasted).",
        ),
    ]
    for notification, expected in cases:
        text, keyboard = notify.message_for(notification, Language.EN)
        assert text == expected
        assert keyboard is None  # MINI_APP_URL isn't HTTPS in tests
