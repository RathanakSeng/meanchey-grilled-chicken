import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer, field_validator

from app.inventory.catalog import Group, Section
from app.models.inventory import ADJUST_REASON_MAX_LENGTH
from app.schemas.common import UserRef

# Same wire format as production weights: a string with 3 decimals ("12.500").
KgOut = Annotated[Decimal, PlainSerializer(lambda v: f"{v:.3f}", return_type=str)]

MovementSource = Literal["production", "adjustment"]
# Why a reversal movement was written (stored in `reason`).
ReversalCause = Literal["reopen", "cancel"]


class InventoryItemOut(BaseModel):
    code: str
    section: Section
    group: Group
    name_en: str
    name_km: str
    tracks_count: bool
    tracks_kg: bool
    # The kg of this item is estimated (wasted pieces: rejected count x average piece weight).
    kg_estimated: bool
    count: int | None
    kg: KgOut | None
    updated_at: datetime | None


class InventorySectionOut(BaseModel):
    section: Section
    items: list[InventoryItemOut]


class InventoryOut(BaseModel):
    sections: list[InventorySectionOut]


class MovementBatch(BaseModel):
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
    kg_estimated: bool
    source: MovementSource
    batch: MovementBatch | None
    step: int | None
    # Set on a reversal: the movement it undoes; `reason` is then "reopen" or "cancel".
    reversal_of: int | None
    # Adjustment: the reason typed by the user. Reversal: "reopen" / "cancel".
    reason: str | None
    balance_count_after: int | None
    balance_kg_after: KgOut | None
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
    kg_estimated: bool
