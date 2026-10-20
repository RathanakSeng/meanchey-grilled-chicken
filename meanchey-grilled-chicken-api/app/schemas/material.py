"""Inventory materials (services/material_service.py has the rules)."""

import re
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

from app.models.inventory import ADJUST_REASON_MAX_LENGTH, MATERIAL_NAME_MAX_LENGTH
from app.schemas.common import UserRef
from app.schemas.inventory import GOut, InventoryUnit, KgOut, M2Out, PrepRole

_SPACES = re.compile(r"\s+")


def _name(value: str) -> str:
    value = _SPACES.sub(" ", value).strip()
    if not value:
        raise ValueError("Name is required")
    if len(value) > MATERIAL_NAME_MAX_LENGTH:
        raise ValueError(f"Name must be at most {MATERIAL_NAME_MAX_LENGTH} characters")
    return value


def _reason(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("Reason is required")
    return value


MaterialName = Annotated[str, Field(max_length=MATERIAL_NAME_MAX_LENGTH * 2), AfterValidator(_name)]
# Checked against the material's unit in the service (precision, > 0, upper bound).
Quantity = Annotated[Decimal, Field(max_digits=14)]


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MaterialCreate(_Body):
    name_km: MaterialName
    name_en: MaterialName
    unit: InventoryUnit


class MaterialUpdate(_Body):
    """Partial. A unit change: kg <-> g always (the balance is converted); to / from count or m²
    only before the material's first movement."""

    name_km: MaterialName | None = None
    name_en: MaterialName | None = None
    unit: InventoryUnit | None = None


class StockAddIn(_Body):
    quantity: Quantity


class StockRemoveIn(_Body):
    quantity: Quantity
    reason: Annotated[
        str, Field(min_length=1, max_length=ADJUST_REASON_MAX_LENGTH), AfterValidator(_reason)
    ]


class MaterialOut(BaseModel):
    id: uuid.UUID
    item_code: str
    name_km: str
    name_en: str
    unit: InventoryUnit
    # e.g. "marinade" (step 2 uses it): can't be archived or switched to count.
    system_code: str | None
    # A picture bundled with the UI, or null (see ItemMaterialOut).
    icon_key: str | None
    # The uploaded icon, versioned (`/inventory/materials/{id}/icon?v=...`), or null.
    icon_url: str | None
    # What preparations may do with it (packaging: moved 1:1 to its prepared twin; satay_sauce /
    # zip_bag_2 / zip_bag_4: satay sachet inputs; none). New materials are packaging; not
    # editable in the UI yet.
    prep_role: PrepRole
    # The balance, in the material's unit (the others are null).
    count: int | None
    kg: KgOut | None
    g: GOut | None
    m2: M2Out | None = None
    # Any movement yet: switching to / from count or m² is then locked (kg <-> g stays allowed).
    has_movements: bool
    archived_at: datetime | None
    archived_by: UserRef | None
    created_by: UserRef | None
    created_at: datetime
    updated_by: UserRef | None
    updated_at: datetime
