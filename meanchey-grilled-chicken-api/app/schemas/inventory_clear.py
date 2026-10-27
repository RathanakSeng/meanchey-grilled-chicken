"""Clear stock (services/inventory_clear_service.py has the rules)."""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, field_validator

from app.inventory.catalog import Group, Section
from app.models.inventory import CLEAR_REASON_MAX_LENGTH
from app.schemas.common import UserRef
from app.schemas.inventory import InventoryUnit

MAX_LINES = 100

ImpactType = Literal["order", "production", "plan", "preparation", "reopen"]
# What the UI says about an impact (i18n key under inventory.clear.impact.*).
ImpactMessage = Literal[
    "order_short",
    "production_step2_short",
    "production_step3_short",
    "plan_sachets_short",
    "preparation_short",
    "reopen_batch_blocked",
    "reopen_preparation_blocked",
]


def _reason(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("Reason is required")
    return value


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ClearLineIn(_Body):
    item_code: Annotated[str, Field(min_length=1, max_length=64)]
    # In the item's main unit (a count for chicken, wings, thighs and packs). Checked against the
    # item's unit in the service (> 0, precision, at most the balance).
    quantity: Annotated[Decimal, Field(max_digits=14)]


class ClearPreviewIn(_Body):
    lines: Annotated[list[ClearLineIn], Field(min_length=1, max_length=MAX_LINES)]

    @field_validator("lines")
    @classmethod
    def _unique(cls, lines: list[ClearLineIn]) -> list[ClearLineIn]:
        codes = [line.item_code for line in lines]
        if len(codes) != len(set(codes)):
            raise ValueError("One line per item")
        return lines


class ClearCreateIn(ClearPreviewIn):
    reason: Annotated[
        str, Field(min_length=1, max_length=CLEAR_REASON_MAX_LENGTH), AfterValidator(_reason)
    ]
    # Required (true) when the clear has impacts: otherwise 409 INVENTORY_CLEAR_UNACKNOWLEDGED.
    acknowledge_impacts: bool = False


class ItemRef(BaseModel):
    item_code: str
    name_en: str
    name_km: str
    section: Section | None = None


class ImpactOut(BaseModel):
    """Something the clear leaves short (it doesn't block the clear)."""

    type: ImpactType
    # The order, batch or preparation code, and its id (for the link).
    code: str
    id: uuid.UUID
    # Production / reopen: the step concerned.
    step: int | None = None
    item_code: str
    name_en: str
    name_km: str
    unit: InventoryUnit
    # In `unit`, as strings in its precision ("20", "1.500").
    needed: str
    available_after: str
    message_key: ImpactMessage


class PreviewLineOut(BaseModel):
    item_code: str
    name_en: str
    name_km: str
    section: Section
    group: Group
    unit: InventoryUnit
    current: str
    clear: str
    after: str
    # Counted items that also track kg (chicken, wings, thighs, wasted pieces): the kg taken.
    kg: str | None = None
    kg_estimated: bool = False
    # The wasted item it moves to; null: removed.
    destination: ItemRef | None


class ClearPreviewOut(BaseModel):
    lines: list[PreviewLineOut]
    impacts: list[ImpactOut]


class ClearLineOut(BaseModel):
    item_code: str
    name_en: str
    name_km: str
    section: Section | None
    unit: InventoryUnit
    # The quantity in `unit`, and the kg of a counted item that tracks it.
    quantity: str
    kg: str | None = None
    kg_estimated: bool = False
    moved_to: ItemRef | None


class ClearOut(BaseModel):
    id: uuid.UUID
    code: str
    reason: str
    lines: list[ClearLineOut]
    # The impacts acknowledged when it was made (as they were then).
    impacts: list[ImpactOut]
    created_by: UserRef | None
    created_at: datetime


class ClearPage(BaseModel):
    items: list[ClearOut]
    total: int
    page: int
    page_size: int
