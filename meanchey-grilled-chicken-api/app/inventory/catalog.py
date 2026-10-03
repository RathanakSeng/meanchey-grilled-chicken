"""Inventory items: what the stock ledger tracks.

Two sections, **stock** and **wasted**. Each item tracks a count, a weight (kg) or both. The
by-product items are generated from the production by-product catalog (`production/catalog.py`),
three per by-product: processed (step 2), packed / carried forward (step 3) and wasted (step 3).
The packs and packed by-products are what orders deliver (`ORDERABLE`); packs that come back
damaged go to the wasted packs, packed by-products to their wasted by-product item.
A new by-product therefore gets its inventory items automatically; its balance row is created on
demand (and at startup), so no migration is needed. Marinade is not tracked.
"""

from dataclasses import dataclass
from typing import Literal

from app.production.catalog import BYPRODUCTS

Section = Literal["stock", "wasted"]
# `production`: changes only through production (finish / reopen / cancel) and orders (delivery,
# returns); no manual changes for anyone. `manual`: set by hand
# (`POST /inventory/items/{code}/set`); none exist yet.
Origin = Literal["production", "manual"]
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
WASTED_PACKS_BIG = "wasted.packs_big"
WASTED_PACKS_SMALL = "wasted.packs_small"


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
