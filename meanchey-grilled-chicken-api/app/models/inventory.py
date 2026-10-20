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
    LargeBinary,
    Numeric,
    SmallInteger,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, utcnow

# order: stock out at Delivering; order_return: returned items back (stock or wasted);
# material_add / material_remove: stock of a material added or taken out by hand;
# material_unit_change: a material switched between kg and g (balance converted) or, with no
# movements yet, to / from m² (an empty balance);
# preparation: a preparation finished (inputs out, outputs in) or reversed (reopen / cancel).
MOVEMENT_SOURCES = (
    "production",
    "adjustment",
    "order",
    "order_return",
    "material_add",
    "material_remove",
    "material_unit_change",
    "preparation",
)
ADJUST_REASON_MAX_LENGTH = 500
INVENTORY_KG = Numeric(12, 3)
# Grams (materials measured in g), 1 decimal.
INVENTORY_G = Numeric(14, 1)
# Square metres (materials measured in m²), 2 decimals.
INVENTORY_M2 = Numeric(14, 2)
MATERIAL_NAME_MAX_LENGTH = 100
MATERIAL_UNITS = ("kg", "g", "m2", "count")
# What a preparation may do with a material (services/preparation_service.py): `packaging` moves
# 1:1 to its prepared twin; `satay_sauce` / `zip_bag_2` / `zip_bag_4` are the satay sachet inputs
# (one material each); `none` isn't preparable. Not editable in the UI yet.
PREP_ROLES = ("none", "packaging", "satay_sauce", "zip_bag_2", "zip_bag_4")
SINGLE_PREP_ROLES = ("satay_sauce", "zip_bag_2", "zip_bag_4")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class InventoryBalance(Base):
    """Current stock of one item. A unit the item doesn't track stays null (a material has
    exactly one of count / kg / g / m2)."""

    __tablename__ = "inventory_balances"
    __table_args__ = (
        CheckConstraint("count >= 0", name="count"),
        CheckConstraint("kg >= 0", name="kg"),
        CheckConstraint("g >= 0", name="g"),
        CheckConstraint("m2 >= 0", name="m2"),
    )

    item_code: Mapped[str] = mapped_column(String(64), primary_key=True)
    count: Mapped[int | None] = mapped_column(Integer)
    kg: Mapped[Decimal | None] = mapped_column(INVENTORY_KG)
    g: Mapped[Decimal | None] = mapped_column(INVENTORY_G)
    m2: Mapped[Decimal | None] = mapped_column(INVENTORY_M2)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )


class InventoryMovement(Base):
    """One change of one item's stock, with the balance after it. Never updated or deleted.

    Sources: production (finish / reopen / cancel; also the marinade a step 2 used), preparation
    (finish / reopen / cancel), order
    (Delivering), order_return (return review), material_add / material_remove (materials, by
    hand), material_unit_change (kg <-> g: the old unit out and the new unit in, one row),
    adjustment (kept for old rows).

    A reversal (reopen / cancel) is a new movement with `reversal_of` pointing at the original;
    the unique index makes sure a movement is reversed at most once.
    """

    __tablename__ = "inventory_movements"
    __table_args__ = (
        CheckConstraint(_in("source", MOVEMENT_SOURCES), name="source"),
        CheckConstraint("step IS NULL OR step BETWEEN 1 AND 3", name="step"),
        CheckConstraint(
            "count_delta IS NOT NULL OR kg_delta IS NOT NULL OR g_delta IS NOT NULL "
            "OR m2_delta IS NOT NULL",
            name="has_delta",
        ),
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
    g_delta: Mapped[Decimal | None] = mapped_column(INVENTORY_G)
    m2_delta: Mapped[Decimal | None] = mapped_column(INVENTORY_M2)
    # The kg was estimated (wasted pieces: rejected count x the batch's average piece weight).
    kg_estimated: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    source: Mapped[str] = mapped_column(String(24))
    batch_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("production_batches.id", ondelete="SET NULL"), index=True
    )
    # Order movements: the order they belong to (their `batch_id` is the batch the stock is
    # attributed to, oldest first at Delivering).
    order_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("orders.id", ondelete="SET NULL"), index=True
    )
    # Preparation movements: the preparation they belong to.
    preparation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("preparations.id", ondelete="SET NULL"), index=True
    )
    step: Mapped[int | None] = mapped_column(SmallInteger)
    reversal_of: Mapped[int | None] = mapped_column(
        ForeignKey("inventory_movements.id", ondelete="RESTRICT")
    )
    reason: Mapped[str | None] = mapped_column(Text)
    balance_count_after: Mapped[int | None] = mapped_column(Integer)
    balance_kg_after: Mapped[Decimal | None] = mapped_column(INVENTORY_KG)
    balance_g_after: Mapped[Decimal | None] = mapped_column(INVENTORY_G)
    balance_m2_after: Mapped[Decimal | None] = mapped_column(INVENTORY_M2)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )


class InventoryMaterial(Base):
    """An inventory item that doesn't come from production (string, skewers, sauces, bags...),
    in the Raw group. Its stock is the balance row of `item_code` and changes through the ledger
    (`material_add` / `material_remove`; production for the marinade). Archived, never deleted.

    `system_code` marks a material the app relies on (`marinade`: step 2 uses it): it can't be
    archived or switched to count.
    """

    __tablename__ = "inventory_materials"
    __table_args__ = (
        CheckConstraint(_in("unit", MATERIAL_UNITS), name="unit"),
        CheckConstraint(
            f"char_length(name_km) BETWEEN 1 AND {MATERIAL_NAME_MAX_LENGTH} "
            f"AND char_length(name_en) BETWEEN 1 AND {MATERIAL_NAME_MAX_LENGTH}",
            name="names",
        ),
        CheckConstraint("(icon IS NULL) = (icon_mime IS NULL)", name="icon_mime"),
        CheckConstraint(_in("prep_role", PREP_ROLES), name="prep_role"),
        # One material per satay sachet input.
        Index(
            "uq_inventory_materials_prep_role",
            "prep_role",
            unique=True,
            postgresql_where=text(_in("prep_role", SINGLE_PREP_ROLES)),
        ),
        # Names unique among active materials, per language, case-insensitive.
        Index(
            "uq_inventory_materials_active_name_km",
            text("lower(name_km)"),
            unique=True,
            postgresql_where=text("archived_at IS NULL"),
        ),
        Index(
            "uq_inventory_materials_active_name_en",
            text("lower(name_en)"),
            unique=True,
            postgresql_where=text("archived_at IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    # material_<8 hex>: the inventory item code (balances, movements).
    item_code: Mapped[str] = mapped_column(String(64), unique=True)
    name_km: Mapped[str] = mapped_column(String(MATERIAL_NAME_MAX_LENGTH))
    name_en: Mapped[str] = mapped_column(String(MATERIAL_NAME_MAX_LENGTH))
    unit: Mapped[str] = mapped_column(String(8))
    system_code: Mapped[str | None] = mapped_column(String(32), unique=True)
    # A picture bundled with the UI (`string`, `marinade`...); null: the unit icon.
    icon_key: Mapped[str | None] = mapped_column(String(32))
    # An uploaded icon (256 px square PNG); shown before `icon_key`. Deferred: only the icon
    # route loads the bytes.
    icon: Mapped[bytes | None] = mapped_column(LargeBinary, deferred=True)
    icon_mime: Mapped[str | None] = mapped_column(String(16))
    # See PREP_ROLES. New materials are packaging (they get a prepared twin).
    prep_role: Mapped[str] = mapped_column(
        String(16), default="packaging", server_default=text("'packaging'")
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    archived_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )
