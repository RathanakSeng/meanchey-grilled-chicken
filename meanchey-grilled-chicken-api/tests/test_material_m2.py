"""Material unit m2 (square metres): 2 decimals, no conversion, unit changes only without
movements, preparation 1:1 with its prepared twin, the four sticker defaults; migration 0023."""

import asyncio

from alembic import command

from tests.conftest import assert_error, auth
from tests.test_material_icons import overview_material
from tests.test_materials import (  # noqa: F401  (gm is a fixture)
    add,
    amount,
    create,
    gm,
    history,
    materials,
    patch,
    remove,
)
from tests.test_migration_step_dates import _alembic, _run
from tests.test_preparations import TWIN, balances, prep  # noqa: F401  (prep is a fixture)
from tests.test_production import ok

STICKERS = {
    "Sticker (4-piece packs) · kg": ("kg", "sticker_4"),
    "Sticker (2-piece packs) · kg": ("kg", "sticker_2"),
    "Sticker (4-piece packs) · m²": ("m2", "sticker_4_m2"),
    "Sticker (2-piece packs) · m²": ("m2", "sticker_2_m2"),
}


async def test_m2_precision_add_remove_never_negative(client, gm) -> None:  # noqa: F811
    m = ok(await create(client, gm, "Roll", "m2"), 201)
    assert m["unit"] == "m2" and m["m2"] == "0.00" and m["kg"] is None and m["g"] is None
    for bad in ("0.001", "12.505", 0, "-1"):
        assert_error(await add(client, gm, m, bad), 422, "VALIDATION_ERROR")
    m = ok(await add(client, gm, m, "12.5"))
    assert m["m2"] == "12.50"
    m = ok(await add(client, gm, m, "0.01"))
    assert m["m2"] == "12.51"
    m = ok(await remove(client, gm, m, "2.5"))
    assert m["m2"] == "10.01"
    r = await remove(client, gm, m, "10.02")
    assert_error(r, 409, "INVENTORY_INSUFFICIENT")
    short = r.json()["error"]["details"]["items"][0]
    assert short["available_m2"] == "10.01" and short["needed_m2"] == "10.02"
    assert short["available_kg"] is None and short["needed_g"] is None
    ok(await remove(client, gm, m, "10.01"))
    rows = await history(client, gm, m["item_code"])
    assert [(r["source"], r["m2_delta"], r["balance_m2_after"]) for r in rows] == [
        ("material_remove", "-10.01", "0.00"),
        ("material_remove", "-2.50", "10.01"),
        ("material_add", "0.01", "12.51"),
        ("material_add", "12.50", "12.50"),
    ]
    assert rows[0]["kg_delta"] is None and rows[0]["g_delta"] is None
    # Too large for one entry.
    assert_error(await add(client, gm, m, "1000000000"), 422, "VALIDATION_ERROR")


async def test_unit_change_to_or_from_m2_only_before_movements(client, gm) -> None:  # noqa: F811
    m = ok(await create(client, gm, "Wrap", "kg"), 201)
    m = ok(await patch(client, gm, m, unit="m2"))
    assert m["unit"] == "m2" and m["m2"] == "0.00" and m["kg"] is None
    m = ok(await patch(client, gm, m, unit="count"))
    m = ok(await patch(client, gm, m, unit="m2"))
    ok(await add(client, gm, m, "3.25"))
    for unit in ("kg", "g", "count"):
        assert_error(await patch(client, gm, m, unit=unit), 409, "MATERIAL_UNIT_LOCKED")
    # The other way: a material with movements can't become m2 either.
    string = (await materials(client, gm))["String"]
    ok(await add(client, gm, string, "1.25"))
    assert_error(await patch(client, gm, string, unit="m2"), 409, "MATERIAL_UNIT_LOCKED")
    # kg <-> g still converts.
    g = ok(await patch(client, gm, string, unit="g"))
    assert g["g"] == "1250.0"
    assert ok(await patch(client, gm, g, unit="kg"))["kg"] == "1.250"


async def test_system_material_never_m2(client, gm) -> None:  # noqa: F811
    marinade = (await materials(client, gm))["Marinade sauce"]
    assert_error(await patch(client, gm, marinade, unit="m2"), 409, "MATERIAL_SYSTEM_LOCKED")


async def test_four_sticker_defaults_with_twins(client, gm) -> None:  # noqa: F811
    found = await materials(client, gm)
    stickers = {n: m for n, m in found.items() if n.startswith("Sticker")}
    assert {n: (m["unit"], m["icon_key"]) for n, m in stickers.items()} == STICKERS
    assert len({m["icon_key"] for m in stickers.values()}) == 4
    assert {m["prep_role"] for m in stickers.values()} == {"packaging"}
    m4 = stickers["Sticker (4-piece packs) · m²"]
    assert m4["name_km"] == "ស្ទីកគ័រ (កញ្ចប់ ៤ ដុំ) · ម៉ែត្រការ៉េ"
    assert stickers["Sticker (2-piece packs) · kg"]["name_km"] == "ស្ទីកគ័រ (កញ្ចប់ ២ ដុំ) · គ.ក"
    assert {amount(m) for m in stickers.values() if m["unit"] == "m2"} == {"0.00"}
    items = await balances(client, gm)
    inventory = ok(await client.get("/inventory", headers=auth(gm)))
    for name in ("Sticker (4-piece packs) · m²", "Sticker (2-piece packs) · m²"):
        m = stickers[name]
        twin = items[m["item_code"] + TWIN]
        assert twin["tracks_m2"] is True and twin["m2"] == "0.00" and twin["kg"] is None
        assert twin["section"] == "prepared"
        assert overview_material(inventory, m["item_code"])["icon_key"] == m["icon_key"]


async def test_preparation_moves_m2_one_to_one(client, gm, prep) -> None:  # noqa: F811
    roll = (await materials(client, gm))["Sticker (4-piece packs) · m²"]
    ok(await add(client, gm, roll, "20.5"))
    p = await prep.create("packaging_material")
    p = ok(await prep.save(p, lines=[{"material_id": roll["id"], "quantity": "7.25"}]))
    assert p["lines"][0]["quantity"] == "7.25" and p["lines"][0]["unit"] == "m2"
    assert p["lines"][0]["material"]["stock"] == "20.50"
    bad = await prep.save(p, lines=[{"material_id": roll["id"], "quantity": "7.255"}])
    assert_error(bad, 422, "VALIDATION_ERROR")
    p = ok(await prep.action(p, "finish"))
    items = await balances(client, gm)
    assert items[roll["item_code"]]["m2"] == "13.25"
    assert items[roll["item_code"] + TWIN]["m2"] == "7.25"
    detail = ok(await client.get(f"/inventory/items/{roll['item_code']}{TWIN}", headers=auth(gm)))
    assert [(s["code"], s["m2"]) for s in detail["preparation_sources"]] == [(p["code"], "7.25")]
    # Reopen puts it back.
    p = ok(await prep.action(p, "reopen"))
    items = await balances(client, gm)
    assert items[roll["item_code"]]["m2"] == "20.50"
    assert items[roll["item_code"] + TWIN]["m2"] == "0.00"
    # Not enough in stock: refused.
    p = ok(await prep.save(p, lines=[{"material_id": roll["id"], "quantity": "20.51"}]))
    assert_error(await prep.action(p, "finish"), 409, "INVENTORY_INSUFFICIENT")


# --- Migration 0023 ------------------------------------------------------------------------------


async def _stickers() -> dict[str, tuple[str, str]]:
    rows = await _run(
        "SELECT icon_key, name_en, unit FROM inventory_materials WHERE icon_key LIKE 'sticker%'"
    )
    return {icon: (name, unit) for icon, name, unit in rows}


async def test_migration_renames_only_seeded_and_creates_once() -> None:
    before = await _stickers()
    assert before["sticker_4"][0] == "Sticker (4-piece packs) · kg" and len(before) == 4
    await asyncio.to_thread(_alembic, command.downgrade, "0022")
    try:
        # The m2 materials are gone; the kg stickers have their old names back.
        assert await _stickers() == {
            "sticker_4": ("Sticker (4-piece packs)", "kg"),
            "sticker_2": ("Sticker (2-piece packs)", "kg"),
        }
        columns = await _run(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'inventory_balances' AND column_name = 'm2'"
        )
        assert columns == []
        # Someone renamed the 2-piece sticker: it keeps its name.
        await _run(
            "UPDATE inventory_materials SET name_en = 'My stickers' WHERE icon_key = 'sticker_2'"
        )
    finally:
        await asyncio.to_thread(_alembic, command.upgrade, "head")
    assert await _stickers() == {
        "sticker_4": ("Sticker (4-piece packs) · kg", "kg"),
        "sticker_2": ("My stickers", "kg"),
        "sticker_4_m2": ("Sticker (4-piece packs) · m²", "m2"),
        "sticker_2_m2": ("Sticker (2-piece packs) · m²", "m2"),
    }
    # Created once, with balances (the material and its prepared twin) and the audit entries.
    codes = await _run("SELECT item_code FROM inventory_materials WHERE unit = 'm2'")
    assert len(codes) == 2
    for (code,) in codes:
        rows = await _run(
            "SELECT item_code, m2 FROM inventory_balances WHERE item_code IN (:a, :b) "
            "ORDER BY item_code",
            a=code,
            b=code + TWIN,
        )
        assert [(r[0], str(r[1])) for r in rows] == [(code, "0.00"), (code + TWIN, "0.00")]
    audit = await _run(
        "SELECT action FROM audit_logs WHERE details->>'source' = 'seed' ORDER BY id"
    )
    assert sorted(audit) == [("material.create",), ("material.create",), ("material.update",)]
