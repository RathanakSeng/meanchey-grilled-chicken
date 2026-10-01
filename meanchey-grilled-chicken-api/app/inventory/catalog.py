"""Inventory items: what the stock ledger tracks.

Two sections, **stock** and **wasted**. Each item tracks a count, a weight (kg) or both. The
by-product items are generated from the production by-product catalog (`production/catalog.py`),
three per by-product: processed (step 2), packed / carried forward (step 3) and wasted (step 3).
A new by-product therefore gets its inventory items automatically; its balance row is created on
demand (and at startup), so no migration is needed. Marinade is not tracked.
"""

from dataclasses import dataclass
from typing import Literal

from app.production.catalog import BYPRODUCTS

Section = Literal["stock", "wasted"]
# Display groups: stock is raw / processed / packed; wasted is its own group.
Group = Literal["raw", "processed", "packed", "wasted"]
SECTIONS: tuple[Section, ...] = ("stock", "wasted")
GROUPS: tuple[Group, ...] = ("raw", "processed", "packed", "wasted")

CHICKEN = "chicken"
WINGS = "wings"
THIGHS = "thighs"
PACKS_BIG = "packs_big"
PACKS_SMALL = "packs_small"
WASTED_WINGS = "wasted.wings"
WASTED_THIGHS = "wasted.thighs"


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
    # average piece weight); adjustments can still set an exact value.
    kg_estimated: bool = False


def _items() -> list[ItemDef]:
    items = [
        ItemDef(CHICKEN, "Chicken", "មាន់", "stock", "raw", True, True, 10),
        ItemDef(WINGS, "Wings", "ស្លាបមាន់", "stock", "processed", True, True, 20),
        ItemDef(THIGHS, "Thighs", "ភ្លៅមាន់", "stock", "processed", True, True, 21),
        ItemDef(PACKS_BIG, "4-Piece Packs", "កញ្ចប់ ៤ ដុំ", "stock", "packed", True, False, 40),
        ItemDef(PACKS_SMALL, "2-Piece Packs", "កញ្ចប់ ២ ដុំ", "stock", "packed", True, False, 41),
        ItemDef(WASTED_WINGS, "Wings", "ស្លាបមាន់", "wasted", "wasted", True, True, 60, True),
        ItemDef(WASTED_THIGHS, "Thighs", "ភ្លៅមាន់", "wasted", "wasted", True, True, 61, True),
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
