"""Inventory items: what the stock ledger tracks.

Two sections, **stock** and **wasted**. Each item tracks a count, a weight (kg) or both. The
by-product items are generated from the production by-product catalog (`production/catalog.py`),
three per by-product: processed (step 2), packed / carried forward (step 3) and wasted (step 3).
The packs and packed by-products are what orders deliver (`ORDERABLE`); packs that come back
damaged go to the wasted packs, packed by-products to their wasted by-product item.
A new by-product therefore gets its inventory items automatically; its balance row is created on
demand (and at startup), so no migration is needed.

**Materials** (string, skewers, sauces, bags...) are not in this catalog: they live in the
`inventory_materials` table (created and archived in the app) and become `ItemDef`s at runtime
(`inventory_service.resolve`), with `origin = manual`, group `raw`, one unit (count, kg, g or m2).
The Marinade sauce material (`system_code = marinade`) is what step 2's marinade comes from.

**Prepared** (section and group `prepared`, origin `preparation`): what preparations make
(services/preparation_service.py). The satay sachets are catalog items here; every packaging
material (`prep_role = packaging`) has a **prepared twin**, `<material item_code>_prepared`, with
the material's names and unit, resolved at runtime like materials (`prepared_def`).
"""

from dataclasses import dataclass
from typing import Literal

from app.production.catalog import BYPRODUCTS

Section = Literal["stock", "prepared", "wasted"]
# `production`: changes only through production (finish / reopen / cancel) and orders (delivery,
# returns); no manual changes for anyone. `manual`: materials, whose stock is added and removed
# by hand (`/inventory/materials/{id}/add|remove`). `preparation`: made only by preparations
# (finish / reopen / cancel); no manual changes either.
Origin = Literal["production", "manual", "preparation"]
# Display groups: stock is raw / processed / packed; prepared and wasted are their own groups.
Group = Literal["raw", "processed", "packed", "prepared", "wasted"]
SECTIONS: tuple[Section, ...] = ("stock", "prepared", "wasted")
GROUPS: tuple[Group, ...] = ("raw", "processed", "packed", "prepared", "wasted")

CHICKEN = "chicken"
WINGS = "wings"
THIGHS = "thighs"
PACKS_BIG = "packs_big"
PACKS_SMALL = "packs_small"
WASTED_WINGS = "wasted.wings"
WASTED_THIGHS = "wasted.thighs"
WASTED_PACKS_BIG = "wasted.packs_big"
WASTED_PACKS_SMALL = "wasted.packs_small"
SATAY_SACHET_2 = "satay_sachet_2"
SATAY_SACHET_4 = "satay_sachet_4"
SATAY_SACHETS: dict[int, str] = {2: SATAY_SACHET_2, 4: SATAY_SACHET_4}


# Materials (inventory_materials, by hand): item codes are MATERIAL_PREFIX + 8 hex characters.
MATERIAL_PREFIX = "material_"
# The material step 2 uses (its marinade_g), found by its system code.
MARINADE = "marinade"
# A packaging material's prepared twin: <material item_code> + PREPARED_SUFFIX.
PREPARED_SUFFIX = "_prepared"


def is_prepared_twin(code: str) -> bool:
    return code.startswith(MATERIAL_PREFIX) and code.endswith(PREPARED_SUFFIX)


def is_material(code: str) -> bool:
    """A raw material's own item (not its prepared twin)."""
    return code.startswith(MATERIAL_PREFIX) and not code.endswith(PREPARED_SUFFIX)


def prepared_code(material_code: str) -> str:
    return f"{material_code}{PREPARED_SUFFIX}"


def twin_base(code: str) -> str:
    """The material item code a prepared twin belongs to."""
    return code[: -len(PREPARED_SUFFIX)]


def byproduct_processed(code: str) -> str:
    return f"byproduct_processed.{code}"


def byproduct_packed(code: str) -> str:
    return f"byproduct_packed.{code}"


def wasted_byproduct(code: str) -> str:
    return f"wasted.byproduct.{code}"


@dataclass(frozen=True)
class ItemDef:
    code: str
    name_en: str
    name_km: str
    section: Section
    group: Group
    tracks_count: bool
    tracks_kg: bool
    order: int
    # Its kg comes from production as an estimate (wasted pieces: rejected count x the batch's
    # average piece weight).
    kg_estimated: bool = False
    origin: Origin = "production"
    # Materials measured in grams (app/inventory/units.py); production items never.
    tracks_g: bool = False
    # Materials measured in square metres.
    tracks_m2: bool = False


def _items() -> list[ItemDef]:
    items = [
        ItemDef(CHICKEN, "Chicken", "មាន់", "stock", "raw", True, True, 10),
        ItemDef(WINGS, "Wings", "ស្លាបមាន់", "stock", "processed", True, True, 20),
        ItemDef(THIGHS, "Thighs", "ភ្លៅមាន់", "stock", "processed", True, True, 21),
        ItemDef(PACKS_BIG, "4-Piece Packs", "កញ្ចប់ ៤ ដុំ", "stock", "packed", True, False, 40),
        ItemDef(PACKS_SMALL, "2-Piece Packs", "កញ្ចប់ ២ ដុំ", "stock", "packed", True, False, 41),
        ItemDef(WASTED_WINGS, "Wings", "ស្លាបមាន់", "wasted", "wasted", True, True, 60, True),
        ItemDef(WASTED_THIGHS, "Thighs", "ភ្លៅមាន់", "wasted", "wasted", True, True, 61, True),
        # Packs returned damaged by a customer (order return review).
        ItemDef(WASTED_PACKS_BIG, "4-Piece Packs", "កញ្ចប់ ៤ ដុំ", "wasted", "wasted", True, False, 62),
        ItemDef(
            WASTED_PACKS_SMALL, "2-Piece Packs", "កញ្ចប់ ២ ដុំ", "wasted", "wasted", True, False, 63
        ),
        # Made by satay sachet preparations (satay sauce + zip bag 7).
        ItemDef(
            SATAY_SACHET_2,
            "Satay sachets (2-piece packs)",
            "សាតេកញ្ចប់ (កញ្ចប់ ២ ដុំ)",
            "prepared",
            "prepared",
            True,
            False,
            55,
            origin="preparation",
        ),
        ItemDef(
            SATAY_SACHET_4,
            "Satay sachets (4-piece packs)",
            "សាតេកញ្ចប់ (កញ្ចប់ ៤ ដុំ)",
            "prepared",
            "prepared",
            True,
            False,
            56,
            origin="preparation",
        ),
    ]
    for b in sorted(BYPRODUCTS, key=lambda b: b.order):
        items += [
            ItemDef(
                byproduct_processed(b.code),
                f"{b.name_en} (processed)",
                f"{b.name_km} (ផលិត)",
                "stock",
                "processed",
                False,
                True,
                30 + b.order,
            ),
            ItemDef(
                byproduct_packed(b.code),
                f"{b.name_en} (packed)",
                f"{b.name_km} (វេចខ្ចប់)",
                "stock",
                "packed",
                False,
                True,
                50 + b.order,
            ),
            ItemDef(
                wasted_byproduct(b.code),
                b.name_en,
                b.name_km,
                "wasted",
                "wasted",
                False,
                True,
                70 + b.order,
            ),
        ]
    return sorted(items, key=lambda i: i.order)


ITEMS: tuple[ItemDef, ...] = tuple(_items())
ITEMS_BY_CODE: dict[str, ItemDef] = {i.code: i for i in ITEMS}

assert len(ITEMS_BY_CODE) == len(ITEMS), "duplicate inventory item code"

# What an order can deliver, in display order: the packs (count) and every packed by-product (kg).
ORDERABLE: tuple[ItemDef, ...] = tuple(i for i in ITEMS if i.group == "packed")
ORDERABLE_CODES: frozenset[str] = frozenset(i.code for i in ORDERABLE)


def wasted_for(code: str) -> str:
    """The wasted item a returned orderable item goes to when it can't go back to stock."""
    if code == PACKS_BIG:
        return WASTED_PACKS_BIG
    if code == PACKS_SMALL:
        return WASTED_PACKS_SMALL
    prefix = byproduct_packed("")
    assert code.startswith(prefix), code
    return wasted_byproduct(code[len(prefix) :])
