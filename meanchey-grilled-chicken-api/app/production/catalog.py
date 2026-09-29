"""Code catalogs for production: by-products and raw material kinds.

Adding a by-product or a material kind is a catalog entry here (plus UI labels if you want
translated names beyond `name_en` / `name_km`); no migration is needed. By-product rows are stored
per batch keyed by `item_code`, and a batch's missing rows are created on demand.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ByproductDef:
    code: str
    name_en: str
    name_km: str
    unit: str
    order: int


@dataclass(frozen=True)
class MaterialKindDef:
    code: str
    name_en: str
    name_km: str
    # Pieces produced from one unit (one chicken): drives the step 2 counts.
    wings_per_unit: int
    thighs_per_unit: int


BYPRODUCTS: tuple[ByproductDef, ...] = (
    ByproductDef("gizzard", "Gizzard", "កោះមាន់", "kg", 1),
    ByproductDef("liver", "Liver", "ថ្លើមមាន់", "kg", 2),
    ByproductDef("heart", "Heart", "បេះដូងមាន់", "kg", 3),
    ByproductDef("head", "Head", "ក្បាលមាន់", "kg", 4),
)
BYPRODUCTS_BY_CODE: dict[str, ByproductDef] = {b.code: b for b in BYPRODUCTS}
BYPRODUCT_CODES: tuple[str, ...] = tuple(b.code for b in sorted(BYPRODUCTS, key=lambda b: b.order))

MATERIAL_KINDS: tuple[MaterialKindDef, ...] = (
    MaterialKindDef("chicken", "Chicken", "មាន់", wings_per_unit=2, thighs_per_unit=2),
)
MATERIAL_KINDS_BY_CODE: dict[str, MaterialKindDef] = {k.code: k for k in MATERIAL_KINDS}
DEFAULT_MATERIAL_KIND = "chicken"

assert DEFAULT_MATERIAL_KIND in MATERIAL_KINDS_BY_CODE
assert len(BYPRODUCTS_BY_CODE) == len(BYPRODUCTS), "duplicate by-product code"
