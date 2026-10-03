"""Order request/response models (services/order_service.py has the rules).

Packs are whole counts, packed by-products kg with 3 decimals: accepted as JSON numbers or
strings, returned as strings ("1.250"), like production and inventory.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

from app.models.order import ORDER_NOTE_MAX_LENGTH, ORDER_REASON_MAX_LENGTH
from app.schemas.common import UserRef
from app.schemas.inventory import KgOut

MAX_ORDER_COUNT = 1_000_000
MAX_BOXES = 200
MAX_LINES_PER_BOX = 50

OrderStatus = Literal[
    "created",
    "delivering",
    "return_pending",
    "success",
    "partly_returned",
    "fully_returned",
    "cancelled",
]
# List filter: one status, or "completed" (success, partly returned, fully returned).
OrderListStatus = Literal[
    "all",
    "created",
    "delivering",
    "return_pending",
    "completed",
    "success",
    "partly_returned",
    "fully_returned",
    "cancelled",
]
BoxColor = Literal["white", "black"]
Unit = Literal["count", "kg"]
Version = Annotated[int, Field(ge=1)]
CountIn = Annotated[int, Field(ge=0, le=MAX_ORDER_COUNT)]
KgIn = Annotated[Decimal, Field(ge=0, max_digits=12, decimal_places=3)]


def _reason(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("Reason is required")
    return value


Reason = Annotated[
    str, Field(min_length=1, max_length=ORDER_REASON_MAX_LENGTH), AfterValidator(_reason)
]


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --- Requests ------------------------------------------------------------------------------------


class OrderLineIn(_Body):
    """`count` for packs (whole, > 0), `kg` for packed by-products (> 0)."""

    item_code: Annotated[str, Field(min_length=1, max_length=64)]
    count: CountIn | None = None
    kg: KgIn | None = None


class OrderBoxIn(_Body):
    color: BoxColor
    lines: Annotated[list[OrderLineIn], Field(max_length=MAX_LINES_PER_BOX)]


class OrderFields(_Body):
    customer_id: uuid.UUID
    # Default: today (BUSINESS_TIMEZONE).
    delivery_date: date | None = None
    driver_id: uuid.UUID | None = None
    note: Annotated[str, Field(max_length=ORDER_NOTE_MAX_LENGTH)] | None = None
    boxes: Annotated[list[OrderBoxIn], Field(max_length=MAX_BOXES)]


class OrderCreate(OrderFields):
    pass


class OrderUpdate(_Body):
    """Partial: only the fields present are changed; `boxes` replaces every box and line."""

    version: Version
    customer_id: uuid.UUID | None = None
    delivery_date: date | None = None
    driver_id: uuid.UUID | None = None
    note: Annotated[str, Field(max_length=ORDER_NOTE_MAX_LENGTH)] | None = None
    boxes: Annotated[list[OrderBoxIn], Field(max_length=MAX_BOXES)] | None = None


class OrderVersionIn(_Body):
    version: Version


class OrderCancelIn(_Body):
    version: Version
    reason: Reason


class ReturnLineIn(_Body):
    item_code: Annotated[str, Field(min_length=1, max_length=64)]
    count: CountIn | None = None
    kg: KgIn | None = None


class DeliveredIn(_Body):
    version: Version
    # accepted: everything accepted (→ success); returned: some items came back (→ return pending).
    outcome: Literal["accepted", "returned"]
    reason: Annotated[str, Field(max_length=ORDER_REASON_MAX_LENGTH)] | None = None
    items: Annotated[list[ReturnLineIn], Field(max_length=100)] = []


class ReviewLineIn(_Body):
    item_code: Annotated[str, Field(min_length=1, max_length=64)]
    to_stock_count: CountIn | None = None
    to_stock_kg: KgIn | None = None
    to_wasted_count: CountIn | None = None
    to_wasted_kg: KgIn | None = None


class ReviewIn(_Body):
    version: Version
    items: Annotated[list[ReviewLineIn], Field(max_length=100)]


# --- Responses -----------------------------------------------------------------------------------


class CustomerBrief(BaseModel):
    id: uuid.UUID
    name: str
    phone_display: str | None
    location: str | None
    is_active: bool


class _ItemRef(BaseModel):
    item_code: str
    name_en: str
    name_km: str
    unit: Unit


class OrderLineOut(_ItemRef):
    count: int | None
    kg: KgOut | None


class OrderBoxOut(BaseModel):
    id: uuid.UUID
    color: BoxColor
    position: int
    lines: list[OrderLineOut]


class SummaryItem(_ItemRef):
    count: int | None
    kg: KgOut | None


class ColorSummary(BaseModel):
    color: BoxColor
    boxes: int
    items: list[SummaryItem]


class TotalSummary(BaseModel):
    boxes: int
    items: list[SummaryItem]


class OrderSummary(BaseModel):
    """Per colour (white, then black; colours without boxes left out) and the grand total.
    Items in catalog order: 4-Piece Packs, 2-Piece Packs, packed by-products."""

    colors: list[ColorSummary]
    total: TotalSummary


class ReturnItemOut(_ItemRef):
    delivered_count: int | None
    delivered_kg: KgOut | None
    returned_count: int | None
    returned_kg: KgOut | None
    # Null until reviewed.
    to_stock_count: int | None
    to_stock_kg: KgOut | None
    to_wasted_count: int | None
    to_wasted_kg: KgOut | None
    reviewed_by: UserRef | None
    reviewed_at: datetime | None


class StockWarning(_ItemRef):
    """An item whose current stock is below the order's total (the hard check is Delivering)."""

    available_count: int | None
    available_kg: KgOut | None
    needed_count: int | None
    needed_kg: KgOut | None


class OrderOut(BaseModel):
    id: uuid.UUID
    code: str
    status: OrderStatus
    customer: CustomerBrief
    delivery_date: date
    driver: UserRef | None
    note: str | None
    return_reason: str | None
    cancel_reason: str | None
    version: int
    created_by: UserRef | None
    created_at: datetime
    updated_by: UserRef | None
    updated_at: datetime
    delivering_by: UserRef | None
    delivering_at: datetime | None
    delivered_by: UserRef | None
    delivered_at: datetime | None
    returns_reviewed_by: UserRef | None
    returns_reviewed_at: datetime | None
    cancelled_by: UserRef | None
    cancelled_at: datetime | None
    boxes: list[OrderBoxOut]
    summary: OrderSummary
    returns: list[ReturnItemOut]
    # Only while Created: items whose stock is below the order's totals right now.
    stock_warnings: list[StockWarning]


class OrderListItem(BaseModel):
    id: uuid.UUID
    code: str
    status: OrderStatus
    customer: CustomerBrief
    delivery_date: date
    driver: UserRef | None
    white_boxes: int
    black_boxes: int
    created_at: datetime
    updated_at: datetime


class OrderPage(BaseModel):
    items: list[OrderListItem]
    total: int
    page: int
    page_size: int


class OrderStats(BaseModel):
    created: int
    delivering: int
    return_pending: int
    # Delivered (success / partly / fully returned / return pending) this month, BUSINESS_TIMEZONE.
    delivered_this_month: int


class CustomerOption(BaseModel):
    id: uuid.UUID
    name: str
    phone_display: str | None


class DriverOption(BaseModel):
    id: uuid.UUID
    full_name: str
    role: Literal["supervisor", "staff"]


class AvailableItem(_ItemRef):
    count: int | None
    kg: KgOut | None
