"""Preparations (services/preparation_service.py has the rules)."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

from app.models.preparation import PREPARATION_NOTE_MAX_LENGTH, PREPARATION_REASON_MAX_LENGTH
from app.schemas.common import UserRef
from app.schemas.inventory import InventoryUnit, PrepRole

PreparationType = Literal["satay_sachet", "packaging_material"]
PreparationStatus = Literal["draft", "finished", "cancelled"]
# The list's status filter: `all` = draft + finished (cancelled only when asked for).
PreparationListStatus = Literal["all", "draft", "finished", "cancelled"]
PackSize = Literal[2, 4]
Version = Annotated[int, Field(ge=1)]
MAX_LINES = 50
# Grams of satay sauce (1 decimal). Material quantities: their precision depends on the material's
# unit (count whole, kg 3, g 1) and is checked by the service.
SatayGramsIn = Annotated[Decimal, Field(ge=0, max_digits=14, decimal_places=1)]
QuantityIn = Annotated[Decimal, Field(ge=0, max_digits=14)]
CountIn = Annotated[int, Field(ge=0, le=10_000_000)]


def _reason(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("Reason is required")
    return value


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --- Requests ------------------------------------------------------------------------------------


class PreparationCreate(_Body):
    type: PreparationType


class PreparationLineIn(_Body):
    """A satay line (`pack_size`, `satay_g`, `zip_bag_qty`, `sachets`) or a packaging line
    (`material_id`, `quantity`), matching the preparation's type. Values may be missing in a
    draft; Finish needs them all, > 0."""

    pack_size: PackSize | None = None
    satay_g: SatayGramsIn | None = None
    zip_bag_qty: QuantityIn | None = None
    sachets: CountIn | None = None
    material_id: uuid.UUID | None = None
    quantity: QuantityIn | None = None


class PreparationDraft(_Body):
    """Draft save. `lines` (when sent) replaces every line; `note` null / "" clears it."""

    version: Version
    lines: Annotated[list[PreparationLineIn], Field(max_length=MAX_LINES)] | None = None
    note: Annotated[str, Field(max_length=PREPARATION_NOTE_MAX_LENGTH)] | None = None


class VersionIn(_Body):
    version: Version


class CancelIn(_Body):
    version: Version
    reason: Annotated[
        str, Field(min_length=1, max_length=PREPARATION_REASON_MAX_LENGTH), AfterValidator(_reason)
    ]


# --- Responses -----------------------------------------------------------------------------------


class PreparationMaterialOut(BaseModel):
    """A material a preparation uses, with what's in stock now (in its unit, as a string with the
    unit's precision: "12", "1.250", "350.0")."""

    id: uuid.UUID
    item_code: str
    name_km: str
    name_en: str
    unit: InventoryUnit
    prep_role: PrepRole
    icon_key: str | None
    icon_url: str | None
    archived: bool
    stock: str
    # Packaging materials: the prepared twin's stock (same unit); null otherwise.
    prepared_stock: str | None = None


class PreparationLineOut(BaseModel):
    id: uuid.UUID
    # Satay lines.
    pack_size: PackSize | None
    satay_g: str | None
    zip_bag_qty: str | None
    sachets: int | None
    # Packaging lines.
    material: PreparationMaterialOut | None
    quantity: str | None
    # The unit of `zip_bag_qty` / `quantity` (the material's when the line was saved).
    unit: InventoryUnit | None


class PreparationItemOut(BaseModel):
    """One item a preparation takes (inputs) or makes (outputs), from its lines."""

    item_code: str
    name_en: str
    name_km: str
    unit: InventoryUnit
    quantity: str
    # A prepared twin or raw material: its material (icon); null for the satay sachets.
    material_id: uuid.UUID | None = None
    icon_key: str | None = None


class SatayMaterialsOut(BaseModel):
    """The satay sachet inputs (by `prep_role`), with their stock; null when none has the role."""

    satay_sauce: PreparationMaterialOut | None
    zip_bag_2: PreparationMaterialOut | None
    zip_bag_4: PreparationMaterialOut | None


class PreparationOut(BaseModel):
    id: uuid.UUID
    code: str
    type: PreparationType
    status: PreparationStatus
    # Recorded at Finish (today in BUSINESS_TIMEZONE); null while a draft.
    prepared_date: date | None
    note: str | None
    cancel_reason: str | None
    version: int
    lines: list[PreparationLineOut]
    # Satay sachet preparations only (the form shows each input's stock).
    satay_materials: SatayMaterialsOut | None
    # What the lines take and make (complete lines' values; a draft shows what Finish would do).
    inputs: list[PreparationItemOut]
    outputs: list[PreparationItemOut]
    created_by: UserRef | None
    created_at: datetime
    updated_by: UserRef | None
    updated_at: datetime
    finished_by: UserRef | None
    finished_at: datetime | None
    cancelled_by: UserRef | None
    cancelled_at: datetime | None


class PreparationListItem(BaseModel):
    id: uuid.UUID
    code: str
    type: PreparationType
    status: PreparationStatus
    prepared_date: date | None
    created_at: datetime
    outputs: list[PreparationItemOut]
    created_by: UserRef | None


class PreparationPage(BaseModel):
    items: list[PreparationListItem]
    total: int
    page: int
    page_size: int


class PreparationStats(BaseModel):
    drafts: int
    # Finished preparations whose prepared date is in the current month (BUSINESS_TIMEZONE).
    finished_this_month: int
    sachets_2_this_month: int
    sachets_4_this_month: int
