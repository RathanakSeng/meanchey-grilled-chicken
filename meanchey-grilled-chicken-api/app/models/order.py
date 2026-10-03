"""Customer orders: boxes of packs and packed by-products, delivered and possibly returned.

```
created ──► delivering ──► return_pending ──► partly_returned | fully_returned
   │            └────────► success
   └──► cancelled
```

- `orders`: one row per order, code OR-YYYYMMDD-NNN (per creation day, `order_counters`).
- `order_boxes`: the boxes of an order, white or black, in order (`position`).
- `order_box_items`: one line per item per box. Packs carry a whole `count`, packed by-products a
  `kg`. Lines are rows so prices (`unit_price`, `amount`) can be added later.
- `order_return_items`: what came back, per item (recorded at Delivered), then how it was split
  into stock and wasted (at the review).

Stock leaves at Delivering (`inventory_movements.source = 'order'`, `order_id` set) and comes back
at the return review (`source = 'order_return'`); see services/order_service.py.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, utcnow

ORDER_STATUSES = (
    "created",
    "delivering",
    "return_pending",
    "success",
    "partly_returned",
    "fully_returned",
    "cancelled",
)
BOX_COLORS = ("white", "black")
ORDER_NOTE_MAX_LENGTH = 1000
ORDER_REASON_MAX_LENGTH = 500
ORDER_KG = Numeric(12, 3)


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def _user_fk() -> Mapped[uuid.UUID | None]:
    return mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


def _at() -> Mapped[datetime | None]:
    return mapped_column(DateTime(timezone=True))


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (
        CheckConstraint(_in("status", ORDER_STATUSES), name="status"),
        CheckConstraint(f"char_length(note) <= {ORDER_NOTE_MAX_LENGTH}", name="note_length"),
        Index("ix_orders_status_delivery_date", "status", "delivery_date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    # OR-YYYYMMDD-NNN, numbered per creation day (BUSINESS_TIMEZONE). Never changes.
    code: Mapped[str] = mapped_column(String(32), unique=True)
    # RESTRICT: customers are deactivated, never deleted. Must be active when chosen.
    customer_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("customers.id", ondelete="RESTRICT"), index=True
    )
    delivery_date: Mapped[date] = mapped_column(Date)
    # An active staff member or supervisor; optional.
    driver_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    note: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        String(16), default="created", server_default=text("'created'")
    )
    # Why the customer returned items (Delivered with returns) / cancelled the order.
    return_reason: Mapped[str | None] = mapped_column(String(ORDER_REASON_MAX_LENGTH))
    cancel_reason: Mapped[str | None] = mapped_column(String(ORDER_REASON_MAX_LENGTH))
    # Optimistic concurrency: every change increments it; writers send the version they saw.
    version: Mapped[int] = mapped_column(Integer, default=1, server_default=text("1"))
    created_by: Mapped[uuid.UUID | None] = _user_fk()
    updated_by: Mapped[uuid.UUID | None] = _user_fk()
    delivering_by: Mapped[uuid.UUID | None] = _user_fk()
    delivered_by: Mapped[uuid.UUID | None] = _user_fk()
    returns_reviewed_by: Mapped[uuid.UUID | None] = _user_fk()
    cancelled_by: Mapped[uuid.UUID | None] = _user_fk()
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )
    delivering_at: Mapped[datetime | None] = _at()
    delivered_at: Mapped[datetime | None] = _at()
    returns_reviewed_at: Mapped[datetime | None] = _at()
    cancelled_at: Mapped[datetime | None] = _at()

    boxes: Mapped[list["OrderBox"]] = relationship(
        lazy="selectin",
        cascade="all, delete-orphan",
        order_by="OrderBox.position",
    )
    returns: Mapped[list["OrderReturnItem"]] = relationship(
        lazy="selectin", cascade="all, delete-orphan", order_by="OrderReturnItem.id"
    )


class OrderBox(Base):
    __tablename__ = "order_boxes"
    __table_args__ = (
        CheckConstraint(_in("color", BOX_COLORS), name="color"),
        CheckConstraint("position >= 1", name="position"),
        UniqueConstraint("order_id", "position", name="uq_order_boxes_order_position"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"))
    # A code, not a free label: it may carry meaning later (e.g. a price list per colour).
    color: Mapped[str] = mapped_column(String(16))
    # 1, 2, 3 … in the order the boxes were entered ("Box 3").
    position: Mapped[int] = mapped_column(SmallInteger)

    lines: Mapped[list["OrderBoxItem"]] = relationship(
        lazy="selectin", cascade="all, delete-orphan", order_by="OrderBoxItem.position"
    )


class OrderBoxItem(Base):
    """One item in one box. `count` for packs (whole, > 0), `kg` for packed by-products (> 0).

    Add `unit_price` / `amount` here when orders get prices."""

    __tablename__ = "order_box_items"
    __table_args__ = (
        CheckConstraint(
            "(count IS NOT NULL AND kg IS NULL AND count > 0) "
            "OR (count IS NULL AND kg IS NOT NULL AND kg > 0)",
            name="quantity",
        ),
        UniqueConstraint("box_id", "item_code", name="uq_order_box_items_box_item"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    box_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("order_boxes.id", ondelete="CASCADE"), index=True
    )
    item_code: Mapped[str] = mapped_column(String(64))
    count: Mapped[int | None] = mapped_column(Integer)
    kg: Mapped[Decimal | None] = mapped_column(ORDER_KG)
    position: Mapped[int] = mapped_column(SmallInteger, default=1, server_default=text("1"))


class OrderReturnItem(Base):
    """What came back of one item, and (after the review) how much went to stock and to wasted.

    Each pair uses the item's unit: counts for packs, kg for packed by-products."""

    __tablename__ = "order_return_items"
    __table_args__ = (
        UniqueConstraint("order_id", "item_code", name="uq_order_return_items_order_item"),
        CheckConstraint(
            "(returned_count IS NOT NULL AND returned_kg IS NULL AND returned_count > 0) "
            "OR (returned_count IS NULL AND returned_kg IS NOT NULL AND returned_kg > 0)",
            name="returned",
        ),
        CheckConstraint(
            "to_stock_count >= 0 AND to_wasted_count >= 0 AND to_stock_kg >= 0 "
            "AND to_wasted_kg >= 0",
            name="split_nonnegative",
        ),
        CheckConstraint(
            "reviewed_at IS NULL OR ("
            "COALESCE(to_stock_count, 0) + COALESCE(to_wasted_count, 0) "
            "= COALESCE(returned_count, 0) "
            "AND COALESCE(to_stock_kg, 0) + COALESCE(to_wasted_kg, 0) = COALESCE(returned_kg, 0))",
            name="split_matches",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    order_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("orders.id", ondelete="CASCADE"), index=True
    )
    item_code: Mapped[str] = mapped_column(String(64))
    returned_count: Mapped[int | None] = mapped_column(Integer)
    returned_kg: Mapped[Decimal | None] = mapped_column(ORDER_KG)
    # Null until reviewed.
    to_stock_count: Mapped[int | None] = mapped_column(Integer)
    to_stock_kg: Mapped[Decimal | None] = mapped_column(ORDER_KG)
    to_wasted_count: Mapped[int | None] = mapped_column(Integer)
    to_wasted_kg: Mapped[Decimal | None] = mapped_column(ORDER_KG)
    reviewed_by: Mapped[uuid.UUID | None] = _user_fk()
    reviewed_at: Mapped[datetime | None] = _at()


class OrderCounter(Base):
    """Last order number used per creation day (codes OR-YYYYMMDD-NNN)."""

    __tablename__ = "order_counters"

    day: Mapped[date] = mapped_column(Date, primary_key=True)
    last_number: Mapped[int] = mapped_column(Integer)
