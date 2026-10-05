"""Inventory materials: defaults, Raw list, units and precision, add / remove, unit change,
archive / restore, system material, duplicate names, the marinade used by step 2, access and
audit."""

from decimal import Decimal

import pytest
from sqlalchemy import delete, select, update

from app.models import AuditLog, InventoryMaterial, ProductionBatch, Role
from app.permissions import registry
from app.services import material_service
from tests.conftest import assert_error, auth, set_marinade_stock
from tests.test_production import PRODUCED, Api, ok

DEFAULT_NAMES = {
    "String": "kg",
    "Skewer": "kg",
    "Sticker (2-piece packs)": "kg",
    "Sticker (4-piece packs)": "kg",
    "Marinade sauce": "g",
    "Satay sauce": "g",
    "Zip bag 7 (2-piece packs)": "kg",
    "Zip bag 7 (4-piece packs)": "kg",
    "Vacuum bag": "kg",
}


@pytest.fixture
async def gm(make_user):
    # GM defaults (Inventory Record, materials Full) plus inventory history.
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


async def materials(client, user, include_archived: bool = False) -> dict[str, dict]:
    url = "/inventory/materials" + ("?include_archived=true" if include_archived else "")
    return {m["name_en"]: m for m in ok(await client.get(url, headers=auth(user)))}


async def create(client, user, name_en: str, unit: str, name_km: str | None = None):
    body = {"name_km": name_km or f"km {name_en}", "name_en": name_en, "unit": unit}
    return await client.post("/inventory/materials", json=body, headers=auth(user))


def add(client, user, m: dict, quantity):
    return client.post(
        f"/inventory/materials/{m['id']}/add", json={"quantity": quantity}, headers=auth(user)
    )


def remove(client, user, m: dict, quantity, reason: str | None = "Broken"):
    body = {"quantity": quantity} | ({"reason": reason} if reason is not None else {})
    return client.post(f"/inventory/materials/{m['id']}/remove", json=body, headers=auth(user))


def patch(client, user, m: dict, **fields):
    return client.patch(f"/inventory/materials/{m['id']}", json=fields, headers=auth(user))


async def history(client, user, code: str) -> list[dict]:
    r = await client.get(f"/inventory/movements?item_code={code}", headers=auth(user))
    return ok(r)["items"]


def amount(m: dict):
    return m[m["unit"]]


# --- Defaults and the Raw list -------------------------------------------------------------------


async def test_defaults_seeded_once(client, session, gm) -> None:
    found = await materials(client, gm)
    assert {name: m["unit"] for name, m in found.items()} == DEFAULT_NAMES
    assert found["Marinade sauce"]["system_code"] == "marinade"
    assert found["Marinade sauce"]["name_km"] == "ទឹកប្រឡាក់"
    assert {m["system_code"] for n, m in found.items() if n != "Marinade sauce"} == {None}
    # Every default starts at 0 (the tests put marinade on hand, conftest).
    assert {amount(m) for n, m in found.items() if n != "Marinade sauce"} == {"0.000", "0.0"}
    assert all(m["item_code"].startswith("material_") for m in found.values())

    # Seeding again changes nothing; an archived default isn't brought back.
    ok(await client.post(f"/inventory/materials/{found['String']['id']}/archive", headers=auth(gm)))
    await material_service.ensure_defaults(session)
    await session.commit()
    assert len(await materials(client, gm, include_archived=True)) == 9
    assert "String" not in await materials(client, gm)

    # Marinade sauce is re-created when it's missing (step 2 needs it).
    await session.execute(
        delete(InventoryMaterial).where(InventoryMaterial.system_code == "marinade")
    )
    await session.commit()
    await material_service.ensure_defaults(session)
    await session.commit()
    again = await materials(client, gm)
    assert again["Marinade sauce"]["system_code"] == "marinade"


async def test_raw_lists_chicken_then_active_materials(client, gm) -> None:
    body = ok(await client.get("/inventory", headers=auth(gm)))
    stock = next(s for s in body["sections"] if s["section"] == "stock")["items"]
    raw = [i for i in stock if i["group"] == "raw"]
    assert raw[0]["code"] == "chicken" and raw[0]["material"] is None
    names = [i["name_en"] for i in raw[1:]]
    assert names == sorted(DEFAULT_NAMES, key=str.lower)
    marinade = next(i for i in raw if i["name_en"] == "Marinade sauce")
    assert marinade["origin"] == "manual" and marinade["tracks_g"] is True
    assert marinade["g"] == "1000000.0" and marinade["kg"] is None and marinade["count"] is None
    assert marinade["material"]["system_code"] == "marinade"
    assert marinade["material"]["unit"] == "g" and marinade["material"]["archived"] is False
    # Item detail works for materials (no per-batch sources).
    detail = ok(await client.get(f"/inventory/items/{marinade['code']}", headers=auth(gm)))
    assert detail["sources"] == [] and detail["g"] == "1000000.0"


# --- Add / remove, precision ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("unit", "bad", "good", "balance"),
    [
        ("count", "1.5", 3, 3),
        ("kg", "0.0005", "1.25", "1.250"),
        ("g", "0.05", "100.5", "100.5"),
    ],
)
async def test_precision_per_unit(client, gm, unit, bad, good, balance) -> None:
    m = ok(await create(client, gm, f"Thing {unit}", unit), 201)
    assert m["unit"] == unit and amount(m) in (0, "0.000", "0.0")
    for value in (bad, 0, "-1"):
        r = await add(client, gm, m, value)
        assert_error(r, 422, "VALIDATION_ERROR")
    m = ok(await add(client, gm, m, good))
    assert amount(m) == balance and m["has_movements"] is True


async def test_add_and_remove_with_reason(client, session, gm) -> None:
    string = (await materials(client, gm))["String"]
    ok(await add(client, gm, string, "1"))
    ok(await add(client, gm, string, "0.5"))
    # A reason is required to take stock out.
    assert_error(await remove(client, gm, string, "0.2", reason=None), 422, "VALIDATION_ERROR")
    assert_error(await remove(client, gm, string, "0.2", reason="   "), 422, "VALIDATION_ERROR")
    after = ok(await remove(client, gm, string, "0.25", reason="Cut for a test batch"))
    assert after["kg"] == "1.250"
    # Never below zero.
    r = await remove(client, gm, string, "2")
    assert_error(r, 409, "INVENTORY_INSUFFICIENT")
    (short,) = r.json()["error"]["details"]["items"]
    assert short["name_en"] == "String"
    assert short["available_kg"] == "1.250" and short["needed_kg"] == "2.000"
    assert (
        ok(await client.get(f"/inventory/items/{string['item_code']}", headers=auth(gm)))["kg"]
        == "1.250"
    )

    rows = await history(client, gm, string["item_code"])
    assert [(r["source"], r["kg_delta"], r["reason"]) for r in rows] == [
        ("material_remove", "-0.250", "Cut for a test batch"),
        ("material_add", "0.500", None),
        ("material_add", "1.000", None),
    ]
    assert rows[0]["balance_kg_after"] == "1.250" and rows[0]["section"] == "stock"
    sauce = (await materials(client, gm))["Satay sauce"]
    ok(await add(client, gm, sauce, "250.5"))
    (row,) = await history(client, gm, sauce["item_code"])
    assert row["g_delta"] == "250.5" and row["balance_g_after"] == "250.5"
    assert row["kg_delta"] is None

    logs = list(
        await session.scalars(
            select(AuditLog)
            .where(AuditLog.entity_type == "material")
            .order_by(AuditLog.created_at, AuditLog.id)
        )
    )
    actions = [(log.action, log.details.get("quantity"), log.details.get("reason")) for log in logs]
    assert actions == [
        ("material.stock_add", "1.000", None),
        ("material.stock_add", "0.500", None),
        ("material.stock_remove", "0.250", "Cut for a test batch"),
        ("material.stock_add", "250.5", None),
    ]
    assert logs[2].details["balance_after"] == "1.250" and logs[2].details["unit"] == "kg"
    # The audit log names the material.
    page = ok(await client.get("/audit-logs?action=material.stock_remove", headers=auth(gm)))
    assert page["items"][0]["entity"]["name"] == "String"


async def test_set_endpoint_refuses_materials(client, gm) -> None:
    string = (await materials(client, gm))["String"]
    r = await client.post(
        f"/inventory/items/{string['item_code']}/set",
        json={"kg": "1", "reason": "x"},
        headers=auth(gm),
    )
    assert_error(r, 409, "INVENTORY_ITEM_PRODUCTION_ONLY")
    assert r.json()["error"]["details"]["use"] == "material_add_remove"


# --- Edit, unit change ---------------------------------------------------------------------------


async def test_unit_change_kg_g_converts(client, gm) -> None:
    string = (await materials(client, gm))["String"]
    ok(await add(client, gm, string, "1.25"))
    m = ok(await patch(client, gm, string, unit="g"))
    assert m["unit"] == "g" and m["g"] == "1250.0" and m["kg"] is None
    ok(await add(client, gm, m, "0.5"))
    # g -> kg rounds to 3 decimals (1250.5 g = 1.2505 kg → 1.251).
    m = ok(await patch(client, gm, m, unit="kg"))
    assert m["kg"] == "1.251"
    rows = await history(client, gm, m["item_code"])
    assert [(r["source"], r["kg_delta"], r["g_delta"]) for r in rows] == [
        ("material_unit_change", "1.251", "-1250.5"),
        ("material_add", None, "0.5"),
        ("material_unit_change", "-1.250", "1250.0"),
        ("material_add", "1.250", None),  # history keeps its original unit
    ]
    assert rows[0]["balance_kg_after"] == "1.251" and rows[0]["balance_g_after"] is None


async def test_unit_change_to_or_from_count_only_before_movements(client, gm) -> None:
    m = ok(await create(client, gm, "Labels", "count"), 201)
    m = ok(await patch(client, gm, m, unit="kg"))
    m = ok(await patch(client, gm, m, unit="count"))
    assert m["unit"] == "count" and m["count"] == 0
    ok(await add(client, gm, m, 5))
    r = await patch(client, gm, m, unit="kg")
    assert_error(r, 409, "MATERIAL_UNIT_LOCKED")
    # Removing everything doesn't unlock it: there are movements.
    ok(await remove(client, gm, m, 5))
    assert_error(await patch(client, gm, m, unit="g"), 409, "MATERIAL_UNIT_LOCKED")


async def test_rename_and_duplicate_names(client, gm) -> None:
    string = (await materials(client, gm))["String"]
    # Case-insensitive, per language, among active materials.
    r = await create(client, gm, "string", "kg", name_km="ថ្មី")
    assert_error(r, 409, "DUPLICATE_MATERIAL_NAME")
    assert r.json()["error"]["details"]["fields"] == ["name_en"]
    r = await create(client, gm, "Twine", "kg", name_km="ខ្សែ")
    assert r.json()["error"]["details"]["fields"] == ["name_km"]
    assert_error(await patch(client, gm, string, name_en="SKEWER"), 409, "DUPLICATE_MATERIAL_NAME")
    renamed = ok(await patch(client, gm, string, name_en="  Cotton   string "))
    assert renamed["name_en"] == "Cotton string"
    # Names are required (trimmed).
    assert_error(await patch(client, gm, string, name_km="  "), 422, "VALIDATION_ERROR")
    assert_error(await create(client, gm, "", "kg"), 422, "VALIDATION_ERROR")
    assert_error(await create(client, gm, "Glue", "litre"), 422, "VALIDATION_ERROR")


# --- Archive / restore, system material ----------------------------------------------------------


async def test_archive_and_restore(client, gm) -> None:
    string = (await materials(client, gm))["String"]
    ok(await add(client, gm, string, "2"))
    archived = ok(
        await client.post(f"/inventory/materials/{string['id']}/archive", headers=auth(gm))
    )
    assert archived["archived_at"] and archived["archived_by"]["id"] == str(gm.id)
    assert archived["kg"] == "2.000"  # balance kept
    assert "String" not in await materials(client, gm)
    assert "String" in await materials(client, gm, include_archived=True)
    body = ok(await client.get("/inventory", headers=auth(gm)))
    assert string["item_code"] not in {i["code"] for s in body["sections"] for i in s["items"]}
    assert_error(await add(client, gm, string, "1"), 409, "MATERIAL_ARCHIVED")
    assert_error(await remove(client, gm, string, "1"), 409, "MATERIAL_ARCHIVED")
    assert len(await history(client, gm, string["item_code"])) == 1  # history kept

    # Its name is free while it's archived; restoring then clashes.
    ok(await create(client, gm, "String", "count", name_km="ខ្សែថ្មី"), 201)
    r = await client.post(f"/inventory/materials/{string['id']}/restore", headers=auth(gm))
    assert_error(r, 409, "DUPLICATE_MATERIAL_NAME")
    new = (await materials(client, gm))["String"]
    ok(await patch(client, gm, new, name_en="String (pieces)"))
    restored = ok(
        await client.post(f"/inventory/materials/{string['id']}/restore", headers=auth(gm))
    )
    assert restored["archived_at"] is None and restored["kg"] == "2.000"
    ok(await add(client, gm, restored, "1"))


async def test_system_material_locks(client, gm) -> None:
    marinade = (await materials(client, gm))["Marinade sauce"]
    r = await client.post(f"/inventory/materials/{marinade['id']}/archive", headers=auth(gm))
    assert_error(r, 409, "MATERIAL_SYSTEM_LOCKED")
    assert_error(await patch(client, gm, marinade, unit="count"), 409, "MATERIAL_SYSTEM_LOCKED")
    m = ok(await patch(client, gm, marinade, name_en="Marinade", unit="kg"))
    assert m["name_en"] == "Marinade" and m["unit"] == "kg" and m["kg"] == "1000.000"
    assert m["system_code"] == "marinade"


async def test_unknown_material(client, gm) -> None:
    fake = {"id": "00000000-0000-0000-0000-000000000000"}
    assert_error(await add(client, gm, fake, 1), 404, "MATERIAL_NOT_FOUND")
    assert_error(await patch(client, gm, fake, name_en="x"), 404, "MATERIAL_NOT_FOUND")


async def test_manage_audit(client, session, gm) -> None:
    m = ok(await create(client, gm, "Gloves", "count"), 201)
    ok(await patch(client, gm, m, name_en="Gloves (pairs)", unit="kg"))
    ok(await patch(client, gm, m, name_en="Gloves (pairs)"))  # no change: no entry
    ok(await client.post(f"/inventory/materials/{m['id']}/archive", headers=auth(gm)))
    ok(await client.post(f"/inventory/materials/{m['id']}/restore", headers=auth(gm)))
    logs = list(
        await session.scalars(
            select(AuditLog)
            .where(AuditLog.entity_type == "material", AuditLog.entity_id == m["id"])
            .order_by(AuditLog.created_at, AuditLog.id)
        )
    )
    assert [log.action for log in logs] == [
        "material.create",
        "material.update",
        "material.archive",
        "material.restore",
    ]
    assert logs[0].details["unit"] == "count"
    assert logs[1].details["changes"]["name_en"] == ["Gloves", "Gloves (pairs)"]
    assert logs[1].details["changes"]["unit"] == ["count", "kg"]
    assert logs[2].details["balance"] == "0.000 kg"


# --- Marinade used by step 2 ---------------------------------------------------------------------


async def marinade(client, gm) -> dict:
    return (await materials(client, gm))["Marinade sauce"]


async def step2_draft(api: Api, supplier: dict, **produced) -> dict:
    batch = await api.step1(supplier)
    return ok(await api.patch(batch, "produced", **(PRODUCED | produced)))


async def test_step2_takes_the_marinade(client, session, api, supplier, gm) -> None:
    await set_marinade_stock(session, Decimal("1000"))
    batch = await step2_draft(api, supplier)
    # The step 2 form shows what's on hand (production.create, step 2 a draft).
    assert batch["marinade_stock"] == {"unit": "g", "count": None, "kg": None, "g": "1000.0"}
    batch = ok(await api.finish(batch, "produced"))
    assert batch["marinade_stock"] is None  # step 2 finished
    m = await marinade(client, gm)
    assert m["g"] == "650.0"
    (row,) = await history(client, gm, m["item_code"])
    assert (row["source"], row["step"], row["g_delta"]) == ("production", 2, "-350.0")
    assert row["batch"]["id"] == batch["id"]
    change = next(c for c in batch["stock_changes"] if c["item_code"] == m["item_code"])
    assert change["g_delta"] == "-350.0" and change["name_en"] == "Marinade sauce"

    # Reopening step 2 puts it back; finishing again takes it again.
    batch = ok(await api.reopen(batch, "produced"))
    assert (await marinade(client, gm))["g"] == "1000.0"
    batch = ok(await api.finish(batch, "produced"))
    assert (await marinade(client, gm))["g"] == "650.0"
    # Reopening step 1 (cascades to step 2) and cancelling put it back too.
    batch = ok(await api.reopen(batch, "raw-material"))
    assert (await marinade(client, gm))["g"] == "1000.0"
    batch = ok(await api.finish(batch, "raw-material"))
    batch = ok(await api.finish(batch, "produced"))
    ok(await api.cancel(batch))
    assert (await marinade(client, gm))["g"] == "1000.0"


async def test_step2_marinade_in_kg(client, session, api, supplier, gm) -> None:
    await set_marinade_stock(session, Decimal("1000"))
    ok(await patch(client, gm, await marinade(client, gm), unit="kg"))  # 1.000 kg
    batch = await step2_draft(api, supplier)
    assert batch["marinade_stock"] == {"unit": "kg", "count": None, "kg": "1.000", "g": None}
    batch = ok(await api.finish(batch, "produced"))
    assert (await marinade(client, gm))["kg"] == "0.650"
    # Switched back to g before the reopen: the reversal is written in g.
    ok(await patch(client, gm, await marinade(client, gm), unit="g"))
    ok(await api.reopen(batch, "produced"))
    assert (await marinade(client, gm))["g"] == "1000.0"


async def test_not_enough_marinade_blocks_finish(client, session, api, supplier, gm) -> None:
    await set_marinade_stock(session, Decimal("100"))
    batch = await step2_draft(api, supplier)
    r = await api.finish(batch, "produced")
    assert_error(r, 409, "INVENTORY_INSUFFICIENT")
    (short,) = r.json()["error"]["details"]["items"]
    assert short["name_en"] == "Marinade sauce" and short["name_km"] == "ទឹកប្រឡាក់"
    assert short["available_g"] == "100.0" and short["needed_g"] == "350.0"
    # Nothing moved: the batch is still at step 2 (draft), chicken still in stock.
    batch = ok(await client.get(f"/production/{batch['id']}", headers=auth(gm)))
    assert batch["produced"]["status"] == "draft"
    assert (await marinade(client, gm))["g"] == "100.0"


async def test_no_marinade_movement_when_zero_or_untracked(
    client, session, api, supplier, gm
) -> None:
    await set_marinade_stock(session, Decimal("1000"))
    batch = await step2_draft(api, supplier, marinade_g="0")
    ok(await api.finish(batch, "produced"))
    m = await marinade(client, gm)
    assert m["g"] == "1000.0" and await history(client, gm, m["item_code"]) == []

    batch = await step2_draft(api, supplier)
    await session.execute(
        update(ProductionBatch)
        .where(ProductionBatch.id == batch["id"])
        .values(inventory_tracked=False)
    )
    await session.commit()
    batch = ok(await client.get(f"/production/{batch['id']}", headers=auth(gm)))
    assert batch["marinade_stock"] is None
    ok(await api.finish(batch, "produced"))
    assert (await marinade(client, gm))["g"] == "1000.0"


# --- Access --------------------------------------------------------------------------------------


def test_registry() -> None:
    inv = registry.FEATURES_BY_CODE["inventory"]
    assert [lv for lv, _ in inv.levels] == ["off", "view", "record"]
    mats = registry.FEATURES_BY_CODE["inventory_materials"]
    assert mats.applies_to == (Role.GENERAL_MANAGER, Role.SUPERVISOR)
    assert mats.level_map == {"off": frozenset(), "full": {"inventory.materials_manage"}}
    d = registry.DEFAULT_PERMISSIONS
    assert {"inventory.materials_stock", "inventory.materials_manage"} <= d[Role.GENERAL_MANAGER]
    assert "inventory.materials_stock" in d[Role.SUPERVISOR]
    assert "inventory.materials_manage" not in d[Role.SUPERVISOR]
    assert not d[Role.STAFF]


async def test_access(client, gm, make_user) -> None:
    sup = await make_user(Role.SUPERVISOR)
    staff = await make_user(Role.STAFF)
    string = (await materials(client, gm))["String"]

    # Staff: Off by default.
    assert_error(
        await client.get("/inventory/materials", headers=auth(staff)), 403, "MISSING_PERMISSION"
    )
    # Supervisor (Inventory Record): adds and removes stock, can't manage materials.
    ok(await add(client, sup, string, "1"))
    ok(await remove(client, sup, string, "0.5"))
    assert_error(await create(client, sup, "Tape", "count"), 403, "MISSING_PERMISSION")
    assert_error(await patch(client, sup, string, name_en="x"), 403, "MISSING_PERMISSION")
    r = await client.post(f"/inventory/materials/{string['id']}/archive", headers=auth(sup))
    assert_error(r, 403, "MISSING_PERMISSION")
    # Archived ones are only listed for managers (silently left out otherwise).
    ok(await client.post(f"/inventory/materials/{string['id']}/archive", headers=auth(gm)))
    assert "String" not in await materials(client, sup, include_archived=True)
    assert "String" in await materials(client, gm, include_archived=True)

    # The supervisor (Staff access) gives staff Inventory View, then Record (its own level).
    r = await client.put(
        f"/users/{staff.id}/features/inventory", json={"level": "view"}, headers=auth(sup)
    )
    assert ok(r)["current_level"] == "view"
    skewer = (await materials(client, staff))["Skewer"]
    assert_error(await add(client, staff, skewer, "1"), 403, "MISSING_PERMISSION")
    r = await client.put(
        f"/users/{staff.id}/features/inventory", json={"level": "record"}, headers=auth(sup)
    )
    assert ok(r)["current_level"] == "record"
    ok(await add(client, staff, skewer, "1"))

    # A supervisor at Inventory View can't give staff Record (capped by its own access).
    sup_view = await make_user(
        Role.SUPERVISOR,
        perms=sorted(registry.DEFAULT_PERMISSIONS[Role.SUPERVISOR] - {"inventory.materials_stock"}),
    )
    other = await make_user(Role.STAFF)
    r = await client.put(
        f"/users/{other.id}/features/inventory", json={"level": "record"}, headers=auth(sup_view)
    )
    assert_error(r, 403, "PERMISSION_NOT_HELD")

    # The GM turns on Inventory materials for the supervisor.
    r = await client.put(
        f"/users/{sup.id}/features/inventory_materials", json={"level": "full"}, headers=auth(gm)
    )
    assert ok(r)["current_level"] == "full"
    ok(await create(client, sup, "Tape", "count"), 201)
