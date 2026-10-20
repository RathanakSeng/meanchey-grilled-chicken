"""Preparations: satay sachets and packaging materials. Drafts (partial values, versions),
Finish (validation per type, movements per line, insufficient stock), reopen / cancel (reversed,
blocked when the outputs are gone), dates, cancelled read-only, prep_role seeds and prepared
twins, codes, stats, list filters and audit."""

import asyncio
from decimal import Decimal

import pytest
from alembic import command
from sqlalchemy import select, update

from app.models import AuditLog, InventoryBalance, InventoryMovement, Role
from app.permissions import registry
from app.services.preparation_service import business_today
from tests.conftest import allow_audit, assert_error, auth
from tests.test_migration_step_dates import _alembic, _run
from tests.test_production import ok

TWIN = "_prepared"


@pytest.fixture
async def gm(make_user):
    # GM defaults (Preparation Record + management Full, Inventory Record, materials Full) plus
    # inventory history.
    return await make_user(
        Role.GENERAL_MANAGER,
        perms=sorted(registry.DEFAULT_PERMISSIONS[Role.GENERAL_MANAGER] | {"inventory.history"}),
    )


class Prep:
    def __init__(self, client, actor) -> None:
        self.client, self.headers = client, auth(actor)

    async def create(self, type_: str) -> dict:
        r = await self.client.post("/preparations", json={"type": type_}, headers=self.headers)
        return ok(r, 201)

    async def get(self, p: dict) -> dict:
        return ok(await self.client.get(f"/preparations/{p['id']}", headers=self.headers))

    def save(self, p: dict, version: int | None = None, **body):
        body = {"version": p["version"] if version is None else version, **body}
        return self.client.patch(f"/preparations/{p['id']}", json=body, headers=self.headers)

    def action(self, p: dict, name: str, version: int | None = None, **body):
        body = {"version": p["version"] if version is None else version, **body}
        return self.client.post(f"/preparations/{p['id']}/{name}", json=body, headers=self.headers)

    async def finished(self, type_: str, lines: list[dict], note: str | None = None) -> dict:
        p = await self.create(type_)
        p = ok(await self.save(p, lines=lines, note=note))
        return ok(await self.action(p, "finish"))


@pytest.fixture
def prep(client, gm) -> Prep:
    return Prep(client, gm)


async def materials(client, user) -> dict[str, dict]:
    rows = ok(await client.get("/inventory/materials", headers=auth(user)))
    return {m["name_en"]: m for m in rows}


async def add_stock(client, user, m: dict, quantity) -> None:
    r = await client.post(
        f"/inventory/materials/{m['id']}/add", json={"quantity": str(quantity)}, headers=auth(user)
    )
    ok(r)


async def balances(client, user) -> dict[str, dict]:
    data = ok(await client.get("/inventory", headers=auth(user)))
    return {i["code"]: i for s in data["sections"] for i in s["items"]}


def amount(item: dict):
    for unit in ("count", "kg", "g", "m2"):
        if item.get(unit) is not None:
            return item[unit]
    return None


@pytest.fixture
async def stocked(client, gm) -> dict[str, dict]:
    """Default materials with stock: satay 1000 g, zip bags 1 kg each, string 5 kg, skewer 3 kg."""
    ms = await materials(client, gm)
    await add_stock(client, gm, ms["Satay sauce"], "1000")
    await add_stock(client, gm, ms["Zip bag 7 (2-piece packs)"], "1")
    await add_stock(client, gm, ms["Zip bag 7 (4-piece packs)"], "1")
    await add_stock(client, gm, ms["String"], "5")
    await add_stock(client, gm, ms["Skewer"], "3")
    return await materials(client, gm)


SATAY_LINES = [
    {"pack_size": 2, "satay_g": "300", "zip_bag_qty": "0.1", "sachets": 40},
    {"pack_size": 4, "satay_g": "250.5", "zip_bag_qty": "0.25", "sachets": 25},
]


# --- prep_role seeds and prepared twins ----------------------------------------------------------


async def test_prep_role_seeds_and_twins(client, gm) -> None:
    ms = await materials(client, gm)
    roles = {name: m["prep_role"] for name, m in ms.items()}
    assert roles == {
        "Marinade sauce": "none",
        "Satay sauce": "satay_sauce",
        "Zip bag 7 (2-piece packs)": "zip_bag_2",
        "Zip bag 7 (4-piece packs)": "zip_bag_4",
        "String": "packaging",
        "Skewer": "packaging",
        "Sticker (2-piece packs) · kg": "packaging",
        "Sticker (4-piece packs) · kg": "packaging",
        "Sticker (2-piece packs) · m²": "packaging",
        "Sticker (4-piece packs) · m²": "packaging",
        "Vacuum bag": "packaging",
    }
    data = ok(await client.get("/inventory", headers=auth(gm)))
    assert [s["section"] for s in data["sections"]] == ["stock", "prepared", "wasted"]
    prepared = data["sections"][1]["items"]
    codes = [i["code"] for i in prepared]
    assert codes[:2] == ["satay_sachet_2", "satay_sachet_4"]
    twins = {i["name_en"]: i for i in prepared[2:]}
    assert set(twins) == {n for n, r in roles.items() if r == "packaging"}
    string = twins["String"]
    assert string["code"] == ms["String"]["item_code"] + TWIN
    assert string["group"] == "prepared" and string["origin"] == "preparation"
    assert string["tracks_kg"] and string["kg"] == "0.000"
    assert string["material"]["icon_key"] == "string"
    # Twins are neither in Raw nor settable.
    raw = {i["code"] for i in data["sections"][0]["items"]}
    assert string["code"] not in raw
    r = await client.post(
        f"/inventory/items/{string['code']}/set",
        json={"kg": "1", "reason": "x"},
        headers=auth(gm),
    )
    assert_error(r, 409, "INVENTORY_ITEM_PRODUCTION_ONLY")


async def test_new_material_defaults_to_packaging_with_a_twin(client, gm) -> None:
    r = await client.post(
        "/inventory/materials",
        json={"name_km": "ខ្សែកៅស៊ូ", "name_en": "Rubber band", "unit": "count"},
        headers=auth(gm),
    )
    m = ok(r, 201)
    assert m["prep_role"] == "packaging"
    items = await balances(client, gm)
    twin = items[m["item_code"] + TWIN]
    assert twin["section"] == "prepared" and twin["count"] == 0 and twin["name_en"] == "Rubber band"
    options = ok(await client.get("/preparations/material-options", headers=auth(gm)))
    assert "Rubber band" in {o["name_en"] for o in options}
    assert "Satay sauce" not in {o["name_en"] for o in options}
    assert "Marinade sauce" not in {o["name_en"] for o in options}


# --- Satay sachets -------------------------------------------------------------------------------


async def test_satay_drafts_finish_and_movements(client, gm, prep, stocked) -> None:
    p = await prep.create("satay_sachet")
    today = business_today()
    assert p["code"] == f"PP-{today:%Y%m%d}-001"
    assert p["status"] == "draft" and p["prepared_date"] is None and p["lines"] == []
    sm = p["satay_materials"]
    assert sm["satay_sauce"]["stock"] == "1000.0" and sm["zip_bag_2"]["stock"] == "1.000"

    # Partial draft: only some values.
    p = ok(await prep.save(p, lines=[{"pack_size": 2, "satay_g": "300"}]))
    assert p["version"] == 2
    assert p["lines"][0]["satay_g"] == "300.0" and p["lines"][0]["sachets"] is None
    # A stale version: conflict with the current preparation.
    r = await prep.save(p, version=1, note="old")
    assert_error(r, 409, "PREPARATION_CONFLICT")
    assert r.json()["error"]["details"]["preparation"]["version"] == 2
    # Finish validates strictly.
    r = await prep.action(p, "finish")
    assert_error(r, 422, "VALIDATION_ERROR")
    locs = {tuple(f["loc"]) for f in r.json()["error"]["details"]["fields"]}
    assert locs == {("lines", "0", "zip_bag_qty"), ("lines", "0", "sachets")}
    # Precision per unit (zip bag in kg: 3 decimals) and fields of the other type.
    r = await prep.save(p, lines=[{"pack_size": 2, "zip_bag_qty": "0.0001"}])
    assert_error(r, 422, "VALIDATION_ERROR")
    r = await prep.save(p, lines=[{"pack_size": 2, "quantity": "1"}])
    assert_error(r, 422, "VALIDATION_ERROR")
    r = await prep.save(p, lines=[{"pack_size": 2}, {"pack_size": 2}])
    assert_error(r, 422, "VALIDATION_ERROR")
    # Both lines, complete.
    p = ok(await prep.save(p, lines=SATAY_LINES, note="  Morning batch  "))
    assert p["note"] == "Morning batch"
    assert [o["item_code"] for o in p["outputs"]] == ["satay_sachet_2", "satay_sachet_4"]
    p = ok(await prep.action(p, "finish"))
    assert p["status"] == "finished" and p["prepared_date"] == today.isoformat()
    assert p["finished_by"]["id"] == str(gm.id)

    items = await balances(client, gm)
    ms = stocked
    assert items[ms["Satay sauce"]["item_code"]]["g"] == "449.5"
    assert items[ms["Zip bag 7 (2-piece packs)"]["item_code"]]["kg"] == "0.900"
    assert items[ms["Zip bag 7 (4-piece packs)"]["item_code"]]["kg"] == "0.750"
    assert items["satay_sachet_2"]["count"] == 40 and items["satay_sachet_4"]["count"] == 25

    movements = ok(
        await client.get(f"/inventory/movements?preparation_id={p['id']}", headers=auth(gm))
    )["items"]
    assert len(movements) == 6
    assert {m["source"] for m in movements} == {"preparation"}
    assert {m["preparation"]["code"] for m in movements} == {p["code"]}
    prepared = ok(await client.get("/inventory/movements?section=prepared", headers=auth(gm)))
    assert {m["item_code"] for m in prepared["items"]} == {"satay_sachet_2", "satay_sachet_4"}

    detail = ok(await client.get("/inventory/items/satay_sachet_2", headers=auth(gm)))
    assert detail["sources"] == []
    assert detail["preparation_sources"] == [
        {
            "preparation_id": p["id"],
            "code": p["code"],
            "prepared_date": today.isoformat(),
            "count": 40,
            "kg": None,
            "g": None,
            "m2": None,
        }
    ]
    # A finished preparation can't be saved or finished again.
    assert_error(await prep.save(p, note="x"), 409, "PREPARATION_INVALID_STATUS")
    assert_error(await prep.action(p, "finish"), 409, "PREPARATION_INVALID_STATUS")


async def test_satay_one_pack_size_and_kg_sauce(client, gm, prep, stocked) -> None:
    sauce = stocked["Satay sauce"]
    r = await client.patch(
        f"/inventory/materials/{sauce['id']}", json={"unit": "kg"}, headers=auth(gm)
    )
    ok(r)
    p = await prep.finished(
        "satay_sachet", [{"pack_size": 4, "satay_g": "125.5", "zip_bag_qty": "0.05", "sachets": 10}]
    )
    items = await balances(client, gm)
    # 1.000 kg − 125.5 g (0.126 kg, rounded half up).
    assert items[sauce["item_code"]]["kg"] == "0.874"
    assert items["satay_sachet_4"]["count"] == 10 and items["satay_sachet_2"]["count"] == 0
    assert p["outputs"] == [
        {
            "item_code": "satay_sachet_4",
            "name_en": "Satay sachets (4-piece packs)",
            "name_km": "សាតេកញ្ចប់ (កញ្ចប់ ៤ ដុំ)",
            "unit": "count",
            "quantity": "10",
            "material_id": None,
            "icon_key": None,
        }
    ]


async def test_finish_needs_lines_and_enough_stock(client, gm, prep, stocked) -> None:
    p = await prep.create("satay_sachet")
    r = await prep.action(p, "finish")
    assert_error(r, 422, "VALIDATION_ERROR")
    p = ok(
        await prep.save(
            p, lines=[{"pack_size": 2, "satay_g": "1500", "zip_bag_qty": "0.1", "sachets": 5}]
        )
    )
    before = await balances(client, gm)
    r = await prep.action(p, "finish")
    assert_error(r, 409, "INVENTORY_INSUFFICIENT")
    short = r.json()["error"]["details"]["items"]
    assert [(i["name_en"], i["available_g"], i["needed_g"]) for i in short] == [
        ("Satay sauce", "1000.0", "1500.0")
    ]
    assert (await prep.get(p))["status"] == "draft"
    assert await balances(client, gm) == before


# --- Packaging materials -------------------------------------------------------------------------


async def test_packaging_moves_one_to_one(client, gm, prep, stocked) -> None:
    # A material in grams and one counted, created in the app (packaging by default).
    gram = ok(
        await client.post(
            "/inventory/materials",
            json={"name_km": "កាវ", "name_en": "Glue", "unit": "g"},
            headers=auth(gm),
        ),
        201,
    )
    counted = ok(
        await client.post(
            "/inventory/materials",
            json={"name_km": "ស្លាក", "name_en": "Label", "unit": "count"},
            headers=auth(gm),
        ),
        201,
    )
    await add_stock(client, gm, gram, "500.5")
    await add_stock(client, gm, counted, "100")
    string, skewer = stocked["String"], stocked["Skewer"]
    p = await prep.create("packaging_material")
    assert p["satay_materials"] is None
    lines = [
        {"material_id": skewer["id"], "quantity": "2"},
        {"material_id": string["id"], "quantity": "0.5"},
        {"material_id": gram["id"], "quantity": "100.5"},
        {"material_id": counted["id"], "quantity": "30"},
    ]
    p = ok(await prep.save(p, lines=lines))
    assert [line["material"]["name_en"] for line in p["lines"]] == [
        "Skewer",
        "String",
        "Glue",
        "Label",
    ]
    assert p["lines"][0]["material"]["stock"] == "3.000"
    assert p["lines"][0]["quantity"] == "2.000" and p["lines"][0]["unit"] == "kg"
    p = ok(await prep.action(p, "finish"))
    items = await balances(client, gm)
    for m, raw_left, moved in (
        (skewer, "1.000", "2.000"),
        (string, "4.500", "0.500"),
        (gram, "400.0", "100.5"),
        (counted, 70, 30),
    ):
        assert amount(items[m["item_code"]]) == raw_left
        twin = items[m["item_code"] + TWIN]
        assert amount(twin) == moved
        assert twin["tracks_kg"] == items[m["item_code"]]["tracks_kg"]
        assert twin["tracks_g"] == items[m["item_code"]]["tracks_g"]
    detail = ok(await client.get(f"/inventory/items/{gram['item_code']}{TWIN}", headers=auth(gm)))
    assert detail["material"]["id"] == gram["id"]
    assert [(s["code"], s["g"]) for s in detail["preparation_sources"]] == [(p["code"], "100.5")]


async def test_packaging_line_rules(client, gm, prep, stocked) -> None:
    p = await prep.create("packaging_material")
    for line in (
        {"material_id": stocked["Satay sauce"]["id"], "quantity": "1"},
        {"material_id": stocked["Marinade sauce"]["id"], "quantity": "1"},
        {"material_id": stocked["String"]["id"], "satay_g": "1"},
        {"quantity": "1"},
        {"material_id": stocked["String"]["id"], "quantity": "0.0005"},
    ):
        assert_error(await prep.save(p, lines=[line]), 422, "VALIDATION_ERROR")
    same = {"material_id": stocked["String"]["id"], "quantity": "1"}
    assert_error(await prep.save(p, lines=[same, same]), 422, "VALIDATION_ERROR")
    p = ok(await prep.save(p, lines=[{"material_id": stocked["String"]["id"]}]))
    r = await prep.action(p, "finish")
    assert_error(r, 422, "VALIDATION_ERROR")
    assert r.json()["error"]["details"]["fields"][0]["loc"] == ["lines", "0", "quantity"]
    # Zero is a valid draft value, not a valid Finish value.
    p = ok(await prep.save(p, lines=[{"material_id": stocked["String"]["id"], "quantity": "0"}]))
    assert_error(await prep.action(p, "finish"), 422, "VALIDATION_ERROR")
    # An archived material can't be prepared.
    p = ok(await prep.save(p, lines=[{"material_id": stocked["String"]["id"], "quantity": "1"}]))
    ok(
        await client.post(
            f"/inventory/materials/{stocked['String']['id']}/archive", headers=auth(gm)
        )
    )
    assert_error(await prep.action(p, "finish"), 409, "MATERIAL_ARCHIVED")


async def test_archived_twin_stays_while_in_stock(client, gm, prep, stocked) -> None:
    string = stocked["String"]
    await prep.finished("packaging_material", [{"material_id": string["id"], "quantity": "1"}])
    ok(await client.post(f"/inventory/materials/{string['id']}/archive", headers=auth(gm)))
    items = await balances(client, gm)
    assert string["item_code"] not in items
    assert items[string["item_code"] + TWIN]["kg"] == "1.000"
    skewer = stocked["Skewer"]
    ok(await client.post(f"/inventory/materials/{skewer['id']}/archive", headers=auth(gm)))
    assert skewer["item_code"] + TWIN not in await balances(client, gm)


async def test_unit_switch_converts_the_twin(client, gm, prep, stocked) -> None:
    string = stocked["String"]
    await prep.finished("packaging_material", [{"material_id": string["id"], "quantity": "1.25"}])
    ok(
        await client.patch(
            f"/inventory/materials/{string['id']}", json={"unit": "g"}, headers=auth(gm)
        )
    )
    items = await balances(client, gm)
    assert items[string["item_code"]]["g"] == "3750.0"
    assert items[string["item_code"] + TWIN]["g"] == "1250.0"
    # Count is locked: the material (and its twin) moved.
    r = await client.patch(
        f"/inventory/materials/{string['id']}", json={"unit": "count"}, headers=auth(gm)
    )
    assert_error(r, 409, "MATERIAL_UNIT_LOCKED")


async def test_draft_line_in_kg_finished_after_switch_to_g(client, gm, prep, stocked) -> None:
    string = stocked["String"]
    p = await prep.create("packaging_material")
    p = ok(await prep.save(p, lines=[{"material_id": string["id"], "quantity": "0.5"}]))
    ok(
        await client.patch(
            f"/inventory/materials/{string['id']}", json={"unit": "g"}, headers=auth(gm)
        )
    )
    p = ok(await prep.action(p, "finish"))
    items = await balances(client, gm)
    assert items[string["item_code"]]["g"] == "4500.0"
    assert items[string["item_code"] + TWIN]["g"] == "500.0"


# --- Reopen and cancel ---------------------------------------------------------------------------


async def test_reopen_reverses_and_refinish(client, gm, prep, stocked) -> None:
    p = await prep.finished("satay_sachet", SATAY_LINES)
    before = await balances(client, gm)
    p = ok(await prep.action(p, "reopen"))
    assert p["status"] == "draft" and p["prepared_date"] is None and p["finished_by"] is None
    assert len(p["lines"]) == 2  # values kept
    items = await balances(client, gm)
    assert items["satay_sachet_2"]["count"] == 0
    assert items[stocked["Satay sauce"]["item_code"]]["g"] == "1000.0"
    movements = ok(
        await client.get(f"/inventory/movements?preparation_id={p['id']}", headers=auth(gm))
    )["items"]
    reversals = [m for m in movements if m["reversal_of"]]
    assert len(reversals) == 6 and {m["reason"] for m in reversals} == {"reopen"}
    assert_error(await prep.action(p, "reopen"), 409, "PREPARATION_INVALID_STATUS")
    p = ok(await prep.action(p, "finish"))
    after = await balances(client, gm)
    assert {k: amount(v) for k, v in after.items()} == {k: amount(v) for k, v in before.items()}


async def test_reopen_and_cancel_blocked_when_outputs_gone(
    client, gm, prep, stocked, session
) -> None:
    string = stocked["String"]
    p = await prep.finished("packaging_material", [{"material_id": string["id"], "quantity": "2"}])
    # The prepared string was used up meanwhile (set directly: no app flow consumes it yet).
    await session.execute(
        update(InventoryBalance)
        .where(InventoryBalance.item_code == string["item_code"] + TWIN)
        .values(kg=Decimal("0.500"))
    )
    await session.commit()
    r = await prep.action(p, "reopen")
    assert_error(r, 409, "INVENTORY_INSUFFICIENT")
    short = r.json()["error"]["details"]["items"][0]
    assert (short["available_kg"], short["needed_kg"]) == ("0.500", "2.000")
    r = await prep.action(p, "cancel", reason="Mistake")
    assert_error(r, 409, "INVENTORY_INSUFFICIENT")
    assert (await prep.get(p))["status"] == "finished"


async def test_cancel_draft_and_finished(client, gm, prep, stocked) -> None:
    draft = await prep.create("satay_sachet")
    assert_error(await prep.action(draft, "cancel", reason="  "), 422, "VALIDATION_ERROR")
    draft = ok(await prep.action(draft, "cancel", reason="Not needed"))
    assert draft["status"] == "cancelled" and draft["cancel_reason"] == "Not needed"
    # Read-only.
    assert_error(await prep.save(draft, note="x"), 409, "PREPARATION_CANCELLED")
    assert_error(await prep.action(draft, "finish"), 409, "PREPARATION_CANCELLED")
    assert_error(await prep.action(draft, "reopen"), 409, "PREPARATION_CANCELLED")
    assert_error(await prep.action(draft, "cancel", reason="x"), 409, "PREPARATION_CANCELLED")

    string = stocked["String"]
    p = await prep.finished("packaging_material", [{"material_id": string["id"], "quantity": "1"}])
    p = ok(await prep.action(p, "cancel", reason="Wrong material"))
    assert p["status"] == "cancelled" and p["prepared_date"] is None
    items = await balances(client, gm)
    assert items[string["item_code"]]["kg"] == "5.000"
    assert items[string["item_code"] + TWIN]["kg"] == "0.000"
    detail = ok(await client.get(f"/inventory/items/{string['item_code']}{TWIN}", headers=auth(gm)))
    assert detail["preparation_sources"] == []


# --- Codes, stats, list, audit -------------------------------------------------------------------


async def test_codes_are_distinct_under_concurrency(client, gm) -> None:
    async def create() -> str:
        r = await client.post("/preparations", json={"type": "satay_sachet"}, headers=auth(gm))
        assert r.status_code == 201, r.text
        return r.json()["code"]

    codes = await asyncio.gather(*(create() for _ in range(6)))
    today = business_today()
    assert sorted(codes) == [f"PP-{today:%Y%m%d}-{n:03d}" for n in range(1, 7)]


async def test_stats_and_list_filters(client, gm, prep, stocked) -> None:
    satay = await prep.finished("satay_sachet", SATAY_LINES)
    string = stocked["String"]
    packaging = await prep.finished(
        "packaging_material", [{"material_id": string["id"], "quantity": "1"}]
    )
    draft = await prep.create("packaging_material")
    cancelled = ok(await prep.action(await prep.create("satay_sachet"), "cancel", reason="x"))

    stats = ok(await client.get("/preparations/stats", headers=auth(gm)))
    assert stats == {
        "drafts": 1,
        "finished_this_month": 2,
        "sachets_2_this_month": 40,
        "sachets_4_this_month": 25,
    }

    async def codes(query: str = "") -> list[str]:
        page = ok(await client.get(f"/preparations?{query}", headers=auth(gm)))
        return [i["code"] for i in page["items"]]

    newest_first = [draft["code"], packaging["code"], satay["code"]]
    assert await codes() == newest_first
    assert cancelled["code"] in await codes("include_cancelled=true")
    assert await codes("status=cancelled") == [cancelled["code"]]
    assert await codes("status=draft") == [draft["code"]]
    assert await codes("type=satay_sachet") == [satay["code"]]
    assert await codes("q=string") == [packaging["code"]]
    assert await codes("q=satay") == [satay["code"]]
    assert await codes(f"q={satay['code']}") == [satay["code"]]
    today = business_today().isoformat()
    assert await codes(f"date_from={today}&date_to={today}") == newest_first
    assert await codes("date_to=2000-01-01") == []
    page = ok(await client.get("/preparations", headers=auth(gm)))
    item = next(i for i in page["items"] if i["code"] == packaging["code"])
    assert item["outputs"][0]["item_code"] == string["item_code"] + TWIN
    assert item["outputs"][0]["quantity"] == "1.000"


async def test_audit_entries(client, gm, prep, stocked, session) -> None:
    p = await prep.finished("satay_sachet", SATAY_LINES)
    ok(await prep.action(p, "reopen"))
    p = await prep.get(p)
    ok(await prep.save(p, note="draft saves aren't audited"))
    p = await prep.get(p)
    ok(await prep.action(p, "cancel", reason="Spoiled"))
    rows = list(
        await session.scalars(
            select(AuditLog).where(AuditLog.entity_type == "preparation").order_by(AuditLog.id)
        )
    )
    assert [r.action for r in rows] == [
        "preparation.create",
        "preparation.finish",
        "preparation.reopen",
        "preparation.cancel",
    ]
    assert {r.details["code"] for r in rows} == {p["code"]}
    assert rows[1].details["sachets_2"] == 40
    assert rows[3].details["reason"] == "Spoiled" and rows[3].details["was"] == "draft"
    await allow_audit(gm)
    logs = ok(await client.get("/audit-logs?entity_type=preparation", headers=auth(gm)))
    assert logs["items"][0]["entity"] == {"type": "preparation", "id": p["id"], "name": p["code"]}
    assert await session.scalar(select(InventoryMovement.id).limit(1)) is not None


# --- Migration 0017 ------------------------------------------------------------------------------


def _roles() -> dict[str, str]:
    rows = asyncio.run(_run("SELECT name_en, prep_role FROM inventory_materials"))
    return dict(rows)


def test_migration_round_trip_backfills_roles() -> None:
    before = _roles()
    assert before["Satay sauce"] == "satay_sauce" and before["Marinade sauce"] == "none"
    _alembic(command.downgrade, "0016")
    try:
        columns = asyncio.run(
            _run(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'inventory_materials' AND column_name = 'prep_role'"
            )
        )
        assert columns == []
    finally:
        _alembic(command.upgrade, "head")
    # Backfilled from the icon keys (Marinade by its system code); the rest stay packaging.
    assert _roles() == before


async def test_migration_downgrade_refused_with_preparations(prep) -> None:
    await prep.create("satay_sachet")
    with pytest.raises(RuntimeError, match="preparation"):
        await asyncio.to_thread(_alembic, command.downgrade, "0016")
    assert "prep_role" in str(
        await _run(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'inventory_materials' AND column_name = 'prep_role'"
        )
    )
