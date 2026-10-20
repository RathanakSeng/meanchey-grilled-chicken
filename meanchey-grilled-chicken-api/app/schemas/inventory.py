import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer, field_validator

from app.inventory.catalog import Group, Origin, Section
from app.models.inventory import ADJUST_REASON_MAX_LENGTH
from app.schemas.common import UserRef

# Same wire format as production weights: a string with 3 decimals ("12.500").
KgOut = Annotated[Decimal, PlainSerializer(lambda v: f"{v:.3f}", return_type=str)]
# Grams: a string with 1 decimal ("350.0"), like production's marinade_g.
GOut = Annotated[Decimal, PlainSerializer(lambda v: f"{v:.1f}", return_type=str)]
# Square metres: a string with 2 decimals ("12.50").
M2Out = Annotated[Decimal, PlainSerializer(lambda v: f"{v:.2f}", return_type=str)]
InventoryUnit = Literal["count", "kg", "g", "m2"]

# order: stock out at Delivering; order_return: returned items (stock or wasted) at the review;
# material_add / material_remove: materials by hand; material_unit_change: kg <-> g switch (or
# an empty balance to / from m²);
# preparation: a preparation finished, reopened or cancelled.
MovementSource = Literal[
    "production",
    "adjustment",
    "order",
    "order_return",
    "material_add",
    "material_remove",
    "material_unit_change",
    "preparation",
]
# What a preparation may do with a material (models/inventory.PREP_ROLES).
PrepRole = Literal["none", "packaging", "satay_sauce", "zip_bag_2", "zip_bag_4"]
# Why a reversal movement was written (stored in `reason`).
ReversalCause = Literal["reopen", "cancel"]


class ItemMaterialOut(BaseModel):
    """Set on materials (origin manual): what the Raw cards and sheets need to act on them."""

    id: uuid.UUID
    unit: InventoryUnit
    # e.g. "marinade": used by production; can't be archived or switched to count.
    system_code: str | None
    archived: bool
    # A picture bundled with the UI (`string`, `marinade`...), or null.
    icon_key: str | None
    # The uploaded icon (GET, inventory.view), versioned so a new upload changes it; null if none.
    # Shown before `icon_key`.
    icon_url: str | None
    # packaging: has a prepared twin (Prepared section); satay_sauce / zip_bag_*: satay sachet
    # inputs; none: not preparable. Not editable in the UI yet.
    prep_role: PrepRole = "packaging"


class InventoryItemOut(BaseModel):
    code: str
    section: Section
    group: Group
    name_en: str
    name_km: str
    tracks_count: bool
    tracks_kg: bool
    # Materials measured in grams.
    tracks_g: bool = False
    # Materials measured in square metres.
    tracks_m2: bool = False
    # The kg of this item is estimated (wasted pieces: rejected count x average piece weight).
    kg_estimated: bool
    # `production`: changes only through production and orders; `manual`: a material.
    origin: Origin
    count: int | None
    kg: KgOut | None
    g: GOut | None = None
    m2: M2Out | None = None
    updated_at: datetime | None
    material: ItemMaterialOut | None = None


class ItemSourceOut(BaseModel):
    """What one batch currently contributes to an item's balance (net of its reversals)."""

    batch_id: uuid.UUID
    code: str
    count: int | None
    kg: KgOut | None
    kg_estimated: bool
    # The latest step of this batch that still contributes (1–3).
    last_step: int


class ItemPreparationSourceOut(BaseModel):
    """What one preparation currently adds to a prepared item (net of its reversals)."""

    preparation_id: uuid.UUID
    code: str
    prepared_date: date | None
    count: int | None
    kg: KgOut | None
    g: GOut | None
    m2: M2Out | None = None


class InventoryItemDetailOut(InventoryItemOut):
    # Production items: the net contribution of each batch (non-zero only), oldest batch first.
    # The totals equal the balance.
    sources: list[ItemSourceOut]
    # Prepared items: the same per preparation (the satay sachets, the prepared twins).
    preparation_sources: list[ItemPreparationSourceOut] = []


class InventorySectionOut(BaseModel):
    section: Section
    items: list[InventoryItemOut]


class InventoryOut(BaseModel):
    sections: list[InventorySectionOut]


class MovementBatch(BaseModel):
    id: uuid.UUID
    code: str


class MovementOrder(BaseModel):
    id: uuid.UUID
    code: str


class MovementPreparation(BaseModel):
    id: uuid.UUID
    code: str


class MovementOut(BaseModel):
    id: int
    item_code: str
    section: Section | None
    name_en: str
    name_km: str
    count_delta: int | None
    kg_delta: KgOut | None
    g_delta: GOut | None = None
    m2_delta: M2Out | None = None
    kg_estimated: bool
    source: MovementSource
    # Production: the batch. Orders: the batch the quantity is attributed to (FIFO).
    batch: MovementBatch | None
    # Order / order_return movements: the order.
    order: MovementOrder | None = None
    # Preparation movements: the preparation.
    preparation: MovementPreparation | None = None
    step: int | None
    # Set on a reversal: the movement it undoes; `reason` is then "reopen" or "cancel".
    reversal_of: int | None
    # Material removed / adjustment: the reason typed by the user. Reversal: "reopen" / "cancel".
    reason: str | None
    balance_count_after: int | None
    balance_kg_after: KgOut | None
    balance_g_after: GOut | None = None
    balance_m2_after: M2Out | None = None
    created_by: UserRef | None
    created_at: datetime


class MovementPage(BaseModel):
    items: list[MovementOut]
    total: int
    page: int
    page_size: int


class SetValueIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    count: int | None = Field(default=None, ge=0, le=10_000_000)
    kg: Decimal | None = Field(default=None, ge=0, le=Decimal("999999999.999"), decimal_places=3)
    reason: str = Field(min_length=1, max_length=ADJUST_REASON_MAX_LENGTH)

    @field_validator("reason")
    @classmethod
    def _strip(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Reason is required")
        return value


class StockChangeOut(BaseModel):
    """A batch's net effect on one item for one finished step (reversed movements left out)."""

    step: int
    item_code: str
    section: Section | None
    name_en: str
    name_km: str
    count_delta: int | None
    kg_delta: KgOut | None
    g_delta: GOut | None = None
    m2_delta: M2Out | None = None
    kg_estimated: bool
