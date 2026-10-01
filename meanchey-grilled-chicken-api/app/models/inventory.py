"""Inventory: a ledger of movements (`inventory_movements`, append-only) plus a balance per item
(`inventory_balances`). Items come from `inventory/catalog.py`; every write goes through
`services.inventory_service.apply_movements`, which locks the balance rows and keeps them >= 0.
"""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, utcnow

MOVEMENT_SOURCES = ("production", "adjustment")
ADJUST_REASON_MAX_LENGTH = 500
INVENTORY_KG = Numeric(12, 3)


class InventoryBalance(Base):
    """Current stock of one item. A unit the item doesn't track stays null."""

    __tablename__ = "inventory_balances"
    __table_args__ = (
        CheckConstraint("count >= 0", name="count"),
        CheckConstraint("kg >= 0", name="kg"),
    )

    item_code: Mapped[str] = mapped_column(String(64), primary_key=True)
    count: Mapped[int | None] = mapped_column(Integer)
    kg: Mapped[Decimal | None] = mapped_column(INVENTORY_KG)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )


class InventoryMovement(Base):
    """One change of one item's stock, with the balance after it. Never updated or deleted.

    A reversal (reopen / cancel) is a new movement with `reversal_of` pointing at the original;
    the unique index makes sure a movement is reversed at most once.
    """

    __tablename__ = "inventory_movements"
    __table_args__ = (
        CheckConstraint("source IN ('production', 'adjustment')", name="source"),
        CheckConstraint("step IS NULL OR step BETWEEN 1 AND 3", name="step"),
        CheckConstraint("count_delta IS NOT NULL OR kg_delta IS NOT NULL", name="has_delta"),
        Index("ix_inventory_movements_item_created", "item_code", "created_at"),
        Index(
            "uq_inventory_movements_reversal_of",
            "reversal_of",
            unique=True,
            postgresql_where=text("reversal_of IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    item_code: Mapped[str] = mapped_column(String(64))
    count_delta: Mapped[int | None] = mapped_column(Integer)
    kg_delta: Mapped[Decimal | None] = mapped_column(INVENTORY_KG)
    # The kg was estimated (wasted pieces: rejected count x the batch's average piece weight).
    kg_estimated: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    source: Mapped[str] = mapped_column(String(16))
    batch_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("production_batches.id", ondelete="SET NULL"), index=True
    )
    step: Mapped[int | None] = mapped_column(SmallInteger)
    reversal_of: Mapped[int | None] = mapped_column(
        ForeignKey("inventory_movements.id", ondelete="RESTRICT")
    )
    reason: Mapped[str | None] = mapped_column(Text)
    balance_count_after: Mapped[int | None] = mapped_column(Integer)
    balance_kg_after: Mapped[Decimal | None] = mapped_column(INVENTORY_KG)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )
