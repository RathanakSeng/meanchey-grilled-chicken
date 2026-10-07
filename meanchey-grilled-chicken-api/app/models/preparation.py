"""Preparations: raw materials turned into ready-to-use materials (not production step 3).

- `preparations`: one row per preparation, code PP-YYYYMMDD-NNN (per creation day,
  `preparation_counters`), one `type`: `satay_sachet` (satay sauce + zip bags → satay sachets) or
  `packaging_material` (a packaging material → its prepared twin, 1:1).
- `preparation_lines`: satay lines (one per pack size: `pack_size`, `satay_g`, `quantity` = zip
  bags used, `sachets`) or packaging lines (one per material: `material_id`, `quantity`).
  `quantity` is in `unit`, the material's unit when the line was saved.

Filled in as a draft (autosave, `version`), locked by Finish, which moves inventory
(`inventory_movements.source = 'preparation'`, `preparation_id` set); see
services/preparation_service.py.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
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

PREPARATION_TYPES = ("satay_sachet", "packaging_material")
PREPARATION_STATUSES = ("draft", "finished", "cancelled")
PACK_SIZES = (2, 4)
PREPARATION_NOTE_MAX_LENGTH = 1000
PREPARATION_REASON_MAX_LENGTH = 500
# Grams of satay sauce (1 decimal) and material quantities (up to 3 decimals: kg).
PREPARATION_G = Numeric(14, 1)
PREPARATION_QTY = Numeric(14, 3)


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def _user_fk() -> Mapped[uuid.UUID | None]:
    return mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


def _at() -> Mapped[datetime | None]:
    return mapped_column(DateTime(timezone=True))


class Preparation(Base):
    __tablename__ = "preparations"
    __table_args__ = (
        CheckConstraint(_in("type", PREPARATION_TYPES), name="type"),
        CheckConstraint(_in("status", PREPARATION_STATUSES), name="status"),
        CheckConstraint(f"char_length(note) <= {PREPARATION_NOTE_MAX_LENGTH}", name="note_length"),
        # The date is recorded at Finish and cleared on reopen.
        CheckConstraint(
            "(status = 'finished') = (prepared_date IS NOT NULL)", name="prepared_date_matches"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    # PP-YYYYMMDD-NNN, numbered per creation day (BUSINESS_TIMEZONE). Never changes.
    code: Mapped[str] = mapped_column(String(32), unique=True)
    type: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16), default="draft", server_default=text("'draft'"))
    # Today in BUSINESS_TIMEZONE at Finish; null while a draft (or cancelled).
    prepared_date: Mapped[date | None] = mapped_column(Date, index=True)
    note: Mapped[str | None] = mapped_column(Text)
    cancel_reason: Mapped[str | None] = mapped_column(String(PREPARATION_REASON_MAX_LENGTH))
    # Optimistic concurrency: every write increments it; writers send the version they saw.
    version: Mapped[int] = mapped_column(Integer, default=1, server_default=text("1"))
    created_by: Mapped[uuid.UUID | None] = _user_fk()
    updated_by: Mapped[uuid.UUID | None] = _user_fk()
    finished_by: Mapped[uuid.UUID | None] = _user_fk()
    cancelled_by: Mapped[uuid.UUID | None] = _user_fk()
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )
    finished_at: Mapped[datetime | None] = _at()
    cancelled_at: Mapped[datetime | None] = _at()

    lines: Mapped[list["PreparationLine"]] = relationship(
        lazy="selectin", cascade="all, delete-orphan", order_by="PreparationLine.position"
    )


class PreparationLine(Base):
    """A satay line (`pack_size` set) or a packaging line (`material_id` set), never both."""

    __tablename__ = "preparation_lines"
    __table_args__ = (
        CheckConstraint(
            "(pack_size IS NOT NULL AND material_id IS NULL) OR "
            "(pack_size IS NULL AND material_id IS NOT NULL AND satay_g IS NULL "
            "AND sachets IS NULL)",
            name="kind",
        ),
        CheckConstraint("pack_size IS NULL OR pack_size IN (2, 4)", name="pack_size"),
        CheckConstraint(
            "(satay_g IS NULL OR satay_g >= 0) AND (quantity IS NULL OR quantity >= 0) "
            "AND (sachets IS NULL OR sachets >= 0)",
            name="nonnegative",
        ),
        CheckConstraint("unit IS NULL OR unit IN ('kg', 'g', 'count')", name="unit"),
        UniqueConstraint("preparation_id", "pack_size", name="uq_preparation_lines_pack_size"),
        UniqueConstraint("preparation_id", "material_id", name="uq_preparation_lines_material"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    preparation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("preparations.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = mapped_column(SmallInteger, default=1, server_default=text("1"))
    # Satay: 2 or 4 (the zip bag and sachet item follow from it).
    pack_size: Mapped[int | None] = mapped_column(SmallInteger)
    # Satay sauce used, always in grams (converted to the material's unit at Finish).
    satay_g: Mapped[Decimal | None] = mapped_column(PREPARATION_G)
    sachets: Mapped[int | None] = mapped_column(Integer)
    # Packaging: the raw material moved to its prepared twin. RESTRICT: archived, never deleted.
    material_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("inventory_materials.id", ondelete="RESTRICT"), index=True
    )
    # Satay: zip bags used; packaging: the quantity moved. In `unit`.
    quantity: Mapped[Decimal | None] = mapped_column(PREPARATION_QTY)
    # The material's unit when the line was last saved (a kg <-> g switch is converted at Finish).
    unit: Mapped[str | None] = mapped_column(String(8))


class PreparationCounter(Base):
    """Last preparation number used per creation day (codes PP-YYYYMMDD-NNN)."""

    __tablename__ = "preparation_counters"

    day: Mapped[date] = mapped_column(Date, primary_key=True)
    last_number: Mapped[int] = mapped_column(Integer)
