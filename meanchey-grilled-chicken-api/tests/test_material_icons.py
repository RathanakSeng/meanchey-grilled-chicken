"""Material icons: bundled `icon_key` on the defaults, upload (type, size, square resize), serve,
delete, versioned `icon_url`, access and audit; migration 0015 round trip."""

import asyncio
import io

import pytest
from alembic import command
from PIL import Image
from sqlalchemy import select

from app.models import AuditLog, Role
from app.services import material_service
from tests.conftest import assert_error, auth
from tests.test_business_info import image
from tests.test_materials import create, gm, materials  # noqa: F401  (gm is a fixture)
from tests.test_migration_step_dates import _alembic, _run
from tests.test_production import ok

ICON_KEYS = {
    "String": "string",
    "Skewer": "skewer",
    "Sticker (2-piece packs)": "sticker_2",
    "Sticker (4-piece packs)": "sticker_4",
    "Marinade sauce": "marinade",
    "Satay sauce": "satay",
    "Zip bag 7 (2-piece packs)": "zip_bag_2",
    "Zip bag 7 (4-piece packs)": "zip_bag_4",
    "Vacuum bag": "vacuum_bag",
}


def upload(client, user, m: dict, data: bytes, name: str = "icon.png", mime: str = "image/png"):
    return client.put(
        f"/inventory/materials/{m['id']}/icon",
        files={"file": (name, data, mime)},
        headers=auth(user),
    )


def overview_material(body: dict, code: str) -> dict:
    return next(i["material"] for s in body["sections"] for i in s["items"] if i["code"] == code)


async def test_defaults_have_bundled_icons(client, gm) -> None:  # noqa: F811
    found = await materials(client, gm)
    assert {name: m["icon_key"] for name, m in found.items()} == ICON_KEYS
    assert {m["icon_url"] for m in found.values()} == {None}
    # A new material has neither: the UI shows its unit icon.
    tape = ok(await create(client, gm, "Tape", "count"), 201)
    assert tape["icon_key"] is None and tape["icon_url"] is None
    inventory = ok(await client.get("/inventory", headers=auth(gm)))
    assert overview_material(inventory, found["String"]["item_code"])["icon_key"] == "string"


async def test_upload_resize_serve_and_delete(client, session, gm) -> None:  # noqa: F811
    string = (await materials(client, gm))["String"]
    # A wide RGB photo: center-cropped and resized to a 256 px square PNG.
    body = ok(await upload(client, gm, string, image("JPEG", 900, 300), "photo.jpg", "image/jpeg"))
    url = body["icon_url"]
    assert url.startswith(f"/inventory/materials/{string['id']}/icon?v=")
    assert body["icon_key"] == "string"  # kept: the upload is shown first
    r = await client.get(url, headers=auth(gm))
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    assert "max-age" in r.headers["cache-control"]
    stored = Image.open(io.BytesIO(r.content))
    assert stored.format == "PNG" and stored.size == (256, 256)

    # The overview and the list carry the same URL; a new upload changes it.
    inventory = ok(await client.get("/inventory", headers=auth(gm)))
    assert overview_material(inventory, string["item_code"])["icon_url"] == url
    body = ok(await upload(client, gm, string, image("WEBP", 64, 64), "icon.webp", "image/webp"))
    assert body["icon_url"] != url
    assert (await materials(client, gm))["String"]["icon_url"] == body["icon_url"]
    # A small image is scaled up to the same square.
    r = await client.get(body["icon_url"], headers=auth(gm))
    assert Image.open(io.BytesIO(r.content)).size == (256, 256)

    body = ok(await client.delete(f"/inventory/materials/{string['id']}/icon", headers=auth(gm)))
    assert body["icon_url"] is None and body["icon_key"] == "string"
    r = await client.get(f"/inventory/materials/{string['id']}/icon", headers=auth(gm))
    assert_error(r, 404, "NOT_FOUND")
    # Deleting again changes nothing.
    ok(await client.delete(f"/inventory/materials/{string['id']}/icon", headers=auth(gm)))

    logs = list(
        await session.scalars(
            select(AuditLog)
            .where(AuditLog.action == "material.update", AuditLog.entity_id == string["id"])
            .order_by(AuditLog.created_at)
        )
    )
    assert [log.details["changes"] for log in logs] == [
        {"icon": "changed"},
        {"icon": "changed"},
        {"icon": "removed"},
    ]
    assert all(log.entity_type == "material" for log in logs)


@pytest.mark.parametrize(
    ("data", "name", "mime"),
    [
        (b"", "empty.png", "image/png"),
        (b"not an image at all", "fake.png", "image/png"),
        (image("GIF"), "anim.gif", "image/gif"),
        (image("BMP"), "icon.png", "image/png"),  # judged by its content, not its name
        (b"\x89PNG" + b"0" * material_service.ICON_MAX_BYTES, "huge.png", "image/png"),
    ],
)
async def test_upload_rejected(client, gm, data, name, mime) -> None:  # noqa: F811
    string = (await materials(client, gm))["String"]
    assert_error(await upload(client, gm, string, data, name, mime), 422, "VALIDATION_ERROR")
    assert (await materials(client, gm))["String"]["icon_url"] is None


async def test_icon_access(client, gm, make_user) -> None:  # noqa: F811
    sup = await make_user(Role.SUPERVISOR)
    staff = await make_user(Role.STAFF)
    string = (await materials(client, gm))["String"]
    url = ok(await upload(client, gm, string, image("PNG", 40, 40)))["icon_url"]
    # Supervisor (Inventory Record, no materials management): sees it, can't change it.
    assert (await client.get(url, headers=auth(sup))).status_code == 200
    assert_error(await upload(client, sup, string, image("PNG")), 403, "MISSING_PERMISSION")
    r = await client.delete(f"/inventory/materials/{string['id']}/icon", headers=auth(sup))
    assert_error(r, 403, "MISSING_PERMISSION")
    # Staff (Inventory Off): not even the picture.
    assert_error(await client.get(url, headers=auth(staff)), 403, "MISSING_PERMISSION")
    r = await client.get(
        "/inventory/materials/00000000-0000-0000-0000-000000000000/icon", headers=auth(gm)
    )
    assert_error(r, 404, "MATERIAL_NOT_FOUND")


def _icon_columns() -> list[tuple[str]]:
    return asyncio.run(
        _run(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'inventory_materials' AND column_name LIKE 'icon%' "
            "ORDER BY column_name"
        )
    )


def test_icons_migration_round_trip() -> None:
    assert _icon_columns() == [("icon",), ("icon_key",), ("icon_mime",)]
    _alembic(command.downgrade, "0014")
    try:
        assert _icon_columns() == []
        # A default seeded without a key gets it back on the way up (archived, so its name
        # doesn't collide with the active Skewer).
        asyncio.run(
            _run(
                "INSERT INTO inventory_materials "
                "(id, item_code, name_km, name_en, unit, archived_at) VALUES "
                "('00000000-0000-0000-0000-0000000000e2', 'material_icon', 'x', 'skewer', 'kg', "
                "now())"
            )
        )
    finally:
        _alembic(command.upgrade, "head")
    assert _icon_columns() == [("icon",), ("icon_key",), ("icon_mime",)]
    rows = asyncio.run(
        _run("SELECT icon_key FROM inventory_materials WHERE item_code = 'material_icon'")
    )
    assert rows == [("skewer",)]
    asyncio.run(_run("DELETE FROM inventory_materials WHERE item_code = 'material_icon'"))
