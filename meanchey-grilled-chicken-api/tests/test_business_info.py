"""Business info (Settings): access (superadmin; a GM only with the feature), validation, phone
normalization, logo upload (type, size, resize), audit, and the preview's data source."""

import io

import pytest
from PIL import Image
from sqlalchemy import select

from app.models import AuditLog, Role
from app.permissions import registry
from tests.conftest import assert_error, auth
from tests.test_orders import Orders, box
from tests.test_production import ok

BODY = {
    "name_km": "មាន់អាំងមានជ័យ",
    "name_en": "Mean Chey Grilled Chicken",
    "address_km": "ផ្ទះលេខ ១២ ផ្លូវ ២៧១\nភ្នំពេញ",
    "address_en": "No. 12, St. 271, Phnom Penh",
    "phone": "012-345-678",
    "footer_note_km": "សូមអរគុណ!",
    "footer_note_en": "Thank you!",
}


def image(fmt: str, width: int = 50, height: int = 20) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (width, height), "white").save(out, format=fmt)
    return out.getvalue()


def upload(client, user, data: bytes, name: str = "logo.png", mime: str = "image/png"):
    return client.put(
        "/settings/business/logo", files={"file": (name, data, mime)}, headers=auth(user)
    )


async def test_seeded_and_superadmin_edits(client, session, superadmin) -> None:
    r = await client.get("/settings/business", headers=auth(superadmin))
    body = ok(r)
    assert body["name_en"] == "Mean Chey Grilled Chicken"
    assert body["name_km"] == "មាន់អាំងមានជ័យ"
    assert body["has_logo"] is False and body["address_en"] is None

    body = ok(await client.put("/settings/business", json=BODY, headers=auth(superadmin)))
    assert body["phone"] == "012345678" and body["phone_display"] == "012 345 678"
    assert body["address_km"] == "ផ្ទះលេខ ១២ ផ្លូវ ២៧១\nភ្នំពេញ"
    assert body["updated_by"]["id"] == str(superadmin.id)

    # Same values again: nothing written.
    ok(await client.put("/settings/business", json=BODY, headers=auth(superadmin)))
    cleared = {**BODY, "address_en": "  ", "footer_note_en": None}
    body = ok(await client.put("/settings/business", json=cleared, headers=auth(superadmin)))
    assert body["address_en"] is None and body["footer_note_en"] is None

    logs = list(
        await session.scalars(
            select(AuditLog)
            .where(AuditLog.action == "settings.business_update")
            .order_by(AuditLog.created_at)
        )
    )
    assert len(logs) == 2
    assert logs[0].details["changes"]["phone"] == [None, "012345678"]
    assert set(logs[1].details["changes"]) == {"address_en", "footer_note_en"}


async def test_gm_only_with_the_feature(client, superadmin, make_user) -> None:
    gm = await make_user(Role.GENERAL_MANAGER)
    assert "settings.business_info" not in registry.DEFAULT_PERMISSIONS[Role.GENERAL_MANAGER]
    for call in (
        client.get("/settings/business", headers=auth(gm)),
        client.put("/settings/business", json=BODY, headers=auth(gm)),
        client.get("/settings/business/preview.pdf", headers=auth(gm)),
        client.delete("/settings/business/logo", headers=auth(gm)),
    ):
        assert_error(await call, 403, "MISSING_PERMISSION")

    r = await client.put(
        f"/users/{gm.id}/features/business_info", json={"level": "full"}, headers=auth(superadmin)
    )
    assert ok(r)["current_level"] == "full"
    ok(await client.get("/settings/business", headers=auth(gm)))
    assert ok(await client.put("/settings/business", json=BODY, headers=auth(gm)))["name_en"]

    # Only the GM can have it: supervisors and staff don't see the feature.
    sup = await make_user(Role.SUPERVISOR)
    r = await client.put(
        f"/users/{sup.id}/features/business_info", json={"level": "full"}, headers=auth(superadmin)
    )
    assert_error(r, 422, "FEATURE_NOT_APPLICABLE")
    for role in (Role.SUPERVISOR, Role.STAFF):
        user = await make_user(role)
        assert_error(
            await client.get("/settings/business", headers=auth(user)), 403, "MISSING_PERMISSION"
        )


async def test_gm_cannot_set_its_own_or_other_features(client, make_user) -> None:
    gm = await make_user(Role.GENERAL_MANAGER)
    r = await client.put(
        f"/users/{gm.id}/features/business_info", json={"level": "full"}, headers=auth(gm)
    )
    assert r.status_code == 403


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("name_km", "   ", "VALIDATION_ERROR"),
        ("name_en", "x" * 201, "VALIDATION_ERROR"),
        ("address_en", "x" * 501, "VALIDATION_ERROR"),
        ("footer_note_km", "x" * 301, "VALIDATION_ERROR"),
        ("phone", "12ab", "INVALID_PHONE"),
    ],
)
async def test_validation(client, superadmin, field, value, code) -> None:
    r = await client.put(
        "/settings/business", json={**BODY, field: value}, headers=auth(superadmin)
    )
    assert_error(r, 422, code)


async def test_missing_and_extra_fields(client, superadmin) -> None:
    r = await client.put("/settings/business", json={"name_km": "x"}, headers=auth(superadmin))
    assert_error(r, 422, "VALIDATION_ERROR")
    r = await client.put("/settings/business", json={**BODY, "logo": "x"}, headers=auth(superadmin))
    assert_error(r, 422, "VALIDATION_ERROR")


async def test_logo_upload_resize_and_remove(client, session, superadmin) -> None:
    body = ok(await upload(client, superadmin, image("PNG", 800, 200)))
    assert body["has_logo"] is True and body["logo_mime"] == "image/png"
    r = await client.get("/settings/business/logo", headers=auth(superadmin))
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    stored = Image.open(io.BytesIO(r.content))
    assert stored.size == (400, 100)  # resized to 400 px wide, same proportions

    # A small JPEG is kept as it is, whatever the file is called.
    jpeg = image("JPEG", 120, 60)
    body = ok(await upload(client, superadmin, jpeg, "photo.png", "image/png"))
    assert body["logo_mime"] == "image/jpeg"
    r = await client.get("/settings/business/logo", headers=auth(superadmin))
    assert r.content == jpeg

    body = ok(await client.delete("/settings/business/logo", headers=auth(superadmin)))
    assert body["has_logo"] is False
    r = await client.get("/settings/business/logo", headers=auth(superadmin))
    assert_error(r, 404, "NOT_FOUND")
    # Removing again: nothing to do, nothing audited.
    ok(await client.delete("/settings/business/logo", headers=auth(superadmin)))

    changes = [
        log.details["changes"]
        for log in await session.scalars(
            select(AuditLog)
            .where(AuditLog.action == "settings.business_update")
            .order_by(AuditLog.created_at)
        )
    ]
    assert changes == [{"logo": "changed"}, {"logo": "changed"}, {"logo": "removed"}]


@pytest.mark.parametrize(
    ("data", "name", "mime"),
    [
        (image("GIF"), "logo.gif", "image/gif"),
        (b"%PDF-1.7 not an image", "logo.png", "image/png"),
        (b"", "logo.png", "image/png"),
        (b"\x89PNG" + b"0" * (500 * 1024), "big.png", "image/png"),
    ],
    ids=["gif", "not-an-image", "empty", "over-500kB"],
)
async def test_logo_rejected(client, superadmin, data, name, mime) -> None:
    assert_error(await upload(client, superadmin, data, name, mime), 422, "VALIDATION_ERROR")
    body = ok(await client.get("/settings/business", headers=auth(superadmin)))
    assert body["has_logo"] is False


async def test_preview_uses_the_latest_order_only_for_order_viewers(
    client, superadmin, make_user, html_documents
) -> None:
    customer = ok(
        await client.post("/customers", json={"name": "Bopha Mart"}, headers=auth(superadmin)),
        201,
    )
    order = await Orders(client, superadmin).create(customer, [box("white", packs_big=2)])
    r = await client.get("/settings/business/preview.pdf", headers=auth(superadmin))
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"
    assert order["code"] in r.text and "SAMPLE" in r.text and "COPY" not in r.text
    # Not counted, not audited.
    assert (await Orders(client, superadmin).get(order))["print_count"] == 0

    # A GM with Business info but without Orders gets made-up data.
    gm = await make_user(Role.GENERAL_MANAGER, perms=["settings.business_info"])
    r = await client.get("/settings/business/preview.pdf", headers=auth(gm))
    assert r.status_code == 200
    assert order["code"] not in r.text and "Sample Shop" in r.text
