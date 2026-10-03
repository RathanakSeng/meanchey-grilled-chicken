"""Delivery notes: content per status, original / COPY counting and audit, access, the Telegram
send (linked, not linked, bot off, Telegram failing), the renderer being unavailable, redaction,
and the real PDF (80 mm wide, height fits the content, Khmer and English text).

Most tests use `html_documents` (the route returns the template's HTML), so they run anywhere;
the `needs_weasyprint` ones render real PDFs and are skipped where Pango isn't installed (plain
Windows). Run the full suite in the API's Docker image to cover them.
"""

import io
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.config import get_settings
from app.documents import delivery_note, render
from app.documents.delivery_note import INVOICE, build_context, kind_for, sample_order
from app.main import app
from app.models import AuditLog, Role
from app.permissions import registry
from tests.conftest import assert_error, auth
from tests.telegram_fakes import RecordingSession
from tests.test_orders import Orders, box
from tests.test_production import Api, ok

MINI_APP = "https://meanchey.example.com"
needs_weasyprint = pytest.mark.skipif(
    render.unavailable_reason() is not None,
    reason="WeasyPrint's system libraries (Pango) aren't installed; run in the Docker image",
)


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
    body = {"name": "Dara <Shop> & Co", "phone": "012 888 777", "location": "Phsar Thmei"}
    return ok(await client.post("/customers", json=body, headers=auth(gm)), 201)


BOXES = [
    box("white", packs_big=3, packs_small=2),
    box("white", packs_big=1),
    box("black", packs_big=2, liver="0.25"),
]


def document(client, user, order: dict):
    return client.get(f"/orders/{order['id']}/document.pdf", headers=auth(user))


async def html(client, user, order: dict) -> str:
    r = await document(client, user, order)
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/pdf"
    assert r.headers["content-disposition"] == f'inline; filename="{order["code"]}.pdf"'
    return r.text


# --- Content per status --------------------------------------------------------------------------


async def test_created_note_shows_everything(client, gm, orders, customer, html_documents) -> None:
    order = await orders.create(customer, BOXES, note="Leave at the back door")
    text = await html(client, gm, order)
    for expected in (
        "ប័ណ្ណដឹកជញ្ជូន",
        "DELIVERY NOTE",
        order["code"],
        "Dara &lt;Shop&gt; &amp; Co",  # escaped
        "012 888 777",
        "Phsar Thmei",
        "អតិថិជន",
        "Customer",
        "White boxes",
        "Black boxes",
        "Box 1",
        "Box 3",
        "Grand total",
        "4-Piece Packs",
        "2-Piece Packs",
        "Liver",
        "0.250 kg",
        "Leave at the back door",
        "Prepared by",
        "Received by",
        "Mean Chey Grilled Chicken",  # business info (seeded name)
    ):
        assert expected in text, expected
    assert "Liver (packed)" not in text  # short names on the receipt
    assert 'class="banner"' not in text and 'class="returns"' not in text
    assert "COPY" not in text
    assert "INVOICE" not in text and "Price" not in text  # prices later
    # Grand total: 3 boxes, 6 × 4-Piece Packs.
    grand = text[text.index('class="grand"') :]
    assert '<td class="num">3</td>' in grand and '<td class="num">6</td>' in grand


async def test_note_per_status(client, gm, api, supplier, orders, customer, html_documents) -> None:
    await api.completed(supplier)
    cancelled = await orders.create(customer, BOXES)
    ok(await orders.cancel(cancelled, "Shop closed today"))
    text = await html(client, gm, cancelled)
    assert 'class="banner"' in text and "CANCELLED" in text and "បានលុបចោល" in text
    assert "Shop closed today" in text

    order = await orders.create(customer, [box("white", packs_big=3)])
    order = ok(await orders.delivering(order))
    text = await html(client, gm, order)
    assert "Delivering" in text and 'class="returns"' not in text

    order = ok(
        await orders.delivered(
            order,
            "returned",
            reason="Two packs crushed",
            items=[{"item_code": "packs_big", "count": 2}],
        )
    )
    text = await html(client, gm, order)
    assert 'class="returns"' in text and "Two packs crushed" in text
    assert "Return pending" in text and "To stock" not in text

    order = ok(
        await orders.review(
            order, [{"item_code": "packs_big", "to_stock_count": 1, "to_wasted_count": 1}]
        )
    )
    text = await html(client, gm, order)
    assert "Partly returned" in text and "To stock" in text and "Wasted" in text

    success = await orders.create(customer, [box("black", packs_small=1)])
    success = ok(await orders.delivering(success))
    success = ok(await orders.delivered(success))
    text = await html(client, gm, success)
    assert "Success" in text and 'class="returns"' not in text


async def test_copy_on_reprint_and_audit(
    client, session, gm, orders, customer, html_documents
) -> None:
    order = await orders.create(customer, BOXES)
    first = await html(client, gm, order)
    assert "COPY" not in first
    second = await html(client, gm, order)
    assert "COPY #2" in second and "ច្បាប់ចម្លង" in second
    third = await html(client, gm, order)
    assert "COPY #3" in third
    after = await orders.get(order)
    assert after["print_count"] == 3
    assert after["version"] == order["version"]  # printing doesn't change the order
    logs = list(
        await session.scalars(
            select(AuditLog)
            .where(AuditLog.action == "order.document_printed")
            .order_by(AuditLog.created_at)
        )
    )
    assert [(log.details["copy"], log.details["via"]) for log in logs] == [
        (1, "download"),
        (2, "download"),
        (3, "download"),
    ]
    assert {log.details["code"] for log in logs} == {order["code"]}
    assert all(log.actor_id == gm.id and log.entity_type == "order" for log in logs)


async def test_access(client, gm, orders, customer, make_user, html_documents) -> None:
    order = await orders.create(customer, BOXES)
    staff = await make_user(Role.STAFF)
    assert_error(await document(client, staff, order), 403, "MISSING_PERMISSION")
    viewer = await make_user(Role.STAFF, perms=["orders.view"])
    assert "DELIVERY NOTE" in await html(client, viewer, order)
    r = await client.get(
        "/orders/00000000-0000-0000-0000-000000000000/document.pdf", headers=auth(gm)
    )
    assert_error(r, 404, "ORDER_NOT_FOUND")


async def test_superadmin_reads_as_system(client, superadmin, gm, customer, html_documents) -> None:
    order = await Orders(client, superadmin).create(customer, BOXES)
    text = await html(client, gm, order)
    assert "System" in text
    assert superadmin.full_name not in text and str(superadmin.id) not in text


async def test_renderer_unavailable(client, gm, orders, customer, monkeypatch) -> None:
    monkeypatch.setattr(render, "unavailable_reason", lambda: "no Pango")
    order = await orders.create(customer, BOXES)
    assert_error(await document(client, gm, order), 503, "DOCUMENT_UNAVAILABLE")
    assert (await orders.get(order))["print_count"] == 0  # nothing counted


# --- Telegram ------------------------------------------------------------------------------------


@pytest.fixture
def tg() -> RecordingSession:
    return RecordingSession()


@pytest.fixture
def webhook_bot(tg, monkeypatch):
    from app.bot.runtime import TelegramRuntime
    from app.bot.setup import create_bot, create_dispatcher

    monkeypatch.setattr(get_settings(), "bot_mode", "webhook")
    monkeypatch.setattr(get_settings(), "mini_app_url", MINI_APP)
    app.state.telegram = TelegramRuntime(
        bot=create_bot(session=tg), dp=create_dispatcher(), secret="s"
    )
    yield tg
    app.state.telegram = None


def send(client, user, order: dict):
    return client.post(f"/orders/{order['id']}/document/send-telegram", headers=auth(user))


async def test_send_to_linked_telegram(
    client, session, gm, orders, customer, webhook_bot, html_documents
) -> None:
    order = await orders.create(customer, BOXES)
    assert ok(await send(client, gm, order)) == {"copy_number": 1}
    (sent,) = webhook_bot.calls("SendDocument")
    assert sent.chat_id == 1001
    assert sent.document.filename == f"{order['code']}.pdf"
    assert b"DELIVERY NOTE" in sent.document.data
    # The QR code points at the order in the Mini App.
    assert b'class="qr"' in sent.document.data
    assert order["code"] in sent.caption and "Dara &lt;Shop&gt; &amp; Co" in sent.caption
    assert ok(await send(client, gm, order)) == {"copy_number": 2}
    assert b"COPY #2" in webhook_bot.calls("SendDocument")[-1].document.data
    log = await session.scalar(
        select(AuditLog).where(AuditLog.action == "order.document_printed").limit(1)
    )
    assert log is not None and log.details["via"] == "telegram"


async def test_send_not_linked(
    client, make_user, orders, customer, webhook_bot, html_documents
) -> None:
    order = await orders.create(customer, BOXES)
    viewer = await make_user(Role.STAFF, perms=["orders.view"])
    assert_error(await send(client, viewer, order), 409, "TELEGRAM_NOT_LINKED")
    assert webhook_bot.calls("SendDocument") == []
    assert (await orders.get(order))["print_count"] == 0


async def test_send_bot_off(client, gm, orders, customer, html_documents) -> None:
    order = await orders.create(customer, BOXES)  # BOT_MODE=off in tests
    assert_error(await send(client, gm, order), 503, "TELEGRAM_NOT_CONFIGURED")


async def test_send_failure_is_not_counted(
    client, session, gm, orders, customer, monkeypatch, html_documents
) -> None:
    from app.bot.runtime import TelegramRuntime
    from app.bot.setup import create_bot, create_dispatcher

    def refuse(method):
        raise RuntimeError("Forbidden: bot was blocked by the user")

    failing = RecordingSession(responses={"SendDocument": refuse})
    monkeypatch.setattr(get_settings(), "bot_mode", "webhook")
    app.state.telegram = TelegramRuntime(
        bot=create_bot(session=failing), dp=create_dispatcher(), secret="s"
    )
    try:
        order = await orders.create(customer, BOXES)
        assert_error(await send(client, gm, order), 502, "TELEGRAM_SEND_FAILED")
    finally:
        app.state.telegram = None
    assert (await orders.get(order))["print_count"] == 0
    logs = await session.scalars(
        select(AuditLog).where(AuditLog.action == "order.document_printed")
    )
    assert list(logs) == []


# --- Template and context (no database) ----------------------------------------------------------


def _context(**overrides) -> dict:
    business = {"name_km": "ហាង", "name_en": "Shop", "phone_display": "012 345 678"}
    args = {
        "printed_at": datetime(2026, 10, 3, 21, 5, tzinfo=UTC),
        "copy": None,
        "app_url": None,
        "logo": None,
    }
    return build_context(sample_order(), business, **{**args, **overrides})


def test_prices_later_switch_to_an_invoice() -> None:
    context = _context()
    assert kind_for(sample_order()) is delivery_note.DELIVERY_NOTE
    assert context["kind"].show_prices is False
    # The same template prints the invoice once orders have prices.
    context["kind"] = INVOICE
    text = render.render_html(context)
    assert "វិក្កយបត្រ" in text and "INVOICE" in text and "Price" in text and "Total amount" in text


def test_logo_qr_and_sample_marker() -> None:
    context = _context(app_url=f"{MINI_APP}/workstation/orders/1", logo=(b"\x89PNG", "image/png"))
    text = render.render_html(context)
    assert 'class="logo" src="data:image/png;base64,' in text
    assert 'class="qr" src="data:image/svg+xml' in text
    assert "SAMPLE" not in text
    assert "SAMPLE" in render.render_html(_context(sample=True))
    # Black and white only: no colour in the stylesheet except black and white.
    css = (render.TEMPLATES / "receipt.css").read_text(encoding="utf-8").lower()
    colours = {c for c in __import__("re").findall(r"#[0-9a-f]{3,6}\b", css)}
    assert colours <= {"#000", "#fff"}


# --- Real PDFs -----------------------------------------------------------------------------------


def _pdf_pages(data: bytes):
    from pypdf import PdfReader

    return PdfReader(io.BytesIO(data)).pages


@needs_weasyprint
async def test_pdf_is_80mm_with_khmer_and_english(
    client, gm, api, supplier, orders, customer
) -> None:
    order = await orders.create(customer, BOXES)
    r = await document(client, gm, order)
    assert r.status_code == 200, r.text
    assert r.content.startswith(b"%PDF")
    (page,) = _pdf_pages(r.content)
    width_mm = float(page.mediabox.width) * 25.4 / 72
    assert abs(width_mm - 80) < 0.1
    text = page.extract_text()
    for expected in (
        order["code"],
        "Dara <Shop> & Co",
        "DELIVERY NOTE",
        "Customer",
        "White boxes",
        "Black boxes",
        "Grand total",
        "0.250 kg",
        "Prepared by",
    ):
        assert expected in text, (expected, text)
    # Khmer text is embedded as Khmer (the font maps glyphs back to Unicode).
    assert any("ក" <= ch <= "៿" for ch in text)

    await api.completed(supplier)
    cancelled = await orders.create(customer, BOXES)
    ok(await orders.cancel(cancelled))
    (page,) = _pdf_pages((await document(client, gm, cancelled)).content)
    assert "CANCELLED" in page.extract_text()
    # The second print of the first order says COPY.
    (page,) = _pdf_pages((await document(client, gm, order)).content)
    assert "COPY #2" in page.extract_text()


@needs_weasyprint
async def test_pdf_height_fits_the_content(client, gm, orders, customer) -> None:
    short = await orders.create(customer, [box("white", packs_big=1)])
    long = await orders.create(customer, [box("black", packs_big=1, liver="0.1")] * 12)
    (short_page,) = _pdf_pages((await document(client, gm, short)).content)
    (long_page,) = _pdf_pages((await document(client, gm, long)).content)
    short_mm = float(short_page.mediabox.height) * 25.4 / 72
    long_mm = float(long_page.mediabox.height) * 25.4 / 72
    assert render.MIN_HEIGHT_MM <= short_mm < 400
    assert long_mm > short_mm + 100  # 11 more boxes


@needs_weasyprint
async def test_business_preview_pdf(client, superadmin) -> None:
    r = await client.get("/settings/business/preview.pdf", headers=auth(superadmin))
    assert r.status_code == 200, r.text
    (page,) = _pdf_pages(r.content)
    assert "SAMPLE" in page.extract_text()


def test_registry_has_no_document_permission() -> None:
    """Printing needs only orders.view: no extra permission to forget on the Access tab."""
    assert not any("document" in p.code for p in registry.PERMISSIONS)
