"""Production batches and their three steps.

A batch (`production_batches`) has one row per step, created when the step becomes available:
raw material (created with the batch), produced (when step 1 is finished) and packaging (when
step 2 is finished). By-products are one row per batch and catalog item (`production/catalog.py`).
Weights are NUMERIC and handled as `Decimal` end to end.
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
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, utcnow

BATCH_STATUSES = ("in_progress", "completed", "cancelled")
STEP_STATUSES = ("draft", "finished")
CANCEL_REASON_MAX_LENGTH = 500
COMMENT_MAX_LENGTH = 1000

KG = Numeric(10, 3)
GRAMS = Numeric(10, 1)


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def _step_status() -> Mapped[str]:
    return mapped_column(String(16), default="draft", server_default=text("'draft'"))


def _user_fk() -> Mapped[uuid.UUID | None]:
    return mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


def _batch_pk() -> Mapped[uuid.UUID]:
    return mapped_column(ForeignKey("production_batches.id", ondelete="CASCADE"), primary_key=True)


class StepMixin:
    """Status and who/when columns shared by the three step tables."""

    status: Mapped[str] = _step_status()
    finished_by: Mapped[uuid.UUID | None] = _user_fk()
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_by: Mapped[uuid.UUID | None] = _user_fk()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )

    @property
    def finished(self) -> bool:
        return self.status == "finished"


class ProductionBatch(Base):
    __tablename__ = "production_batches"
    __table_args__ = (
        CheckConstraint(_in("status", BATCH_STATUSES), name="status"),
        CheckConstraint("current_step BETWEEN 1 AND 3", name="current_step"),
        Index("ix_production_batches_status_step", "status", "current_step"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    # PR-YYYYMMDD-NNN, numbered per day of the date given at creation. Never renumbered.
    code: Mapped[str] = mapped_column(String(32), unique=True)
    production_date: Mapped[date] = mapped_column(Date, index=True)
    status: Mapped[str] = mapped_column(
        String(16), default="in_progress", server_default=text("'in_progress'")
    )
    # The step being worked on (1–3); 3 once the batch is completed.
    current_step: Mapped[int] = mapped_column(SmallInteger, default=1, server_default=text("1"))
    cancel_reason: Mapped[str | None] = mapped_column(String(CANCEL_REASON_MAX_LENGTH))
    # Optimistic concurrency: every change increments it; writers send the version they saw.
    version: Mapped[int] = mapped_column(Integer, default=1, server_default=text("1"))
    created_by: Mapped[uuid.UUID | None] = _user_fk()
    updated_by: Mapped[uuid.UUID | None] = _user_fk()
    cancelled_by: Mapped[uuid.UUID | None] = _user_fk()
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    raw_material: Mapped["ProductionRawMaterial"] = relationship(
        lazy="selectin", cascade="all, delete-orphan"
    )
    output: Mapped["ProductionOutput | None"] = relationship(
        lazy="selectin", cascade="all, delete-orphan"
    )
    packaging: Mapped["ProductionPackaging | None"] = relationship(
        lazy="selectin", cascade="all, delete-orphan"
    )
    byproducts: Mapped[list["ProductionByproduct"]] = relationship(
        lazy="selectin", cascade="all, delete-orphan"
    )


class ProductionRawMaterial(StepMixin, Base):
    """Step 1. The batch's `production_date` is edited with this step."""

    __tablename__ = "production_raw_materials"
    __table_args__ = (
        CheckConstraint(_in("status", STEP_STATUSES), name="status"),
        CheckConstraint("weight_kg >= 0", name="weight_kg"),
        CheckConstraint("quantity >= 0", name="quantity"),
    )

    batch_id: Mapped[uuid.UUID] = _batch_pk()
    # Nullable while a draft; RESTRICT: suppliers are deactivated, never deleted.
    supplier_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("suppliers.id", ondelete="RESTRICT"), index=True
    )
    material_kind: Mapped[str] = mapped_column(String(32))
    weight_kg: Mapped[Decimal | None] = mapped_column(KG)
    quantity: Mapped[int | None] = mapped_column(Integer)


class ProductionOutput(StepMixin, Base):
    """Step 2. Piece counts are computed by the server from the step 1 quantity."""

    __tablename__ = "production_outputs"
    __table_args__ = (
        CheckConstraint(_in("status", STEP_STATUSES), name="status"),
        CheckConstraint("wings_kg >= 0 AND thighs_kg >= 0 AND marinade_g >= 0", name="nonnegative"),
    )

    batch_id: Mapped[uuid.UUID] = _batch_pk()
    wings_kg: Mapped[Decimal | None] = mapped_column(KG)
    thighs_kg: Mapped[Decimal | None] = mapped_column(KG)
    wings_count: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    thighs_count: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    marinade_g: Mapped[Decimal | None] = mapped_column(GRAMS)


class ProductionPackaging(StepMixin, Base):
    """Step 3 (standardize)."""

    __tablename__ = "production_packaging"
    __table_args__ = (
        CheckConstraint(_in("status", STEP_STATUSES), name="status"),
        CheckConstraint(
            "big_packages >= 0 AND small_packages >= 0 "
            "AND rejected_wings >= 0 AND rejected_thighs >= 0",
            name="nonnegative",
        ),
    )

    batch_id: Mapped[uuid.UUID] = _batch_pk()
    big_packages: Mapped[int | None] = mapped_column(Integer)
    small_packages: Mapped[int | None] = mapped_column(Integer)
    rejected_wings: Mapped[int | None] = mapped_column(Integer)
    rejected_thighs: Mapped[int | None] = mapped_column(Integer)
    comment: Mapped[str | None] = mapped_column(Text)


class ProductionByproduct(Base):
    """Produced kg (step 2), then carried forward / rejected kg (step 3), per catalog item."""

    __tablename__ = "production_byproducts"
    __table_args__ = (
        CheckConstraint(
            "produced_kg >= 0 AND carry_kg >= 0 AND rejected_kg >= 0", name="nonnegative"
        ),
    )

    batch_id: Mapped[uuid.UUID] = _batch_pk()
    item_code: Mapped[str] = mapped_column(String(32), primary_key=True)
    produced_kg: Mapped[Decimal | None] = mapped_column(KG)
    carry_kg: Mapped[Decimal | None] = mapped_column(KG)
    rejected_kg: Mapped[Decimal | None] = mapped_column(KG)


class ProductionBatchCounter(Base):
    """Last batch number used per production date (codes PR-YYYYMMDD-NNN)."""

    __tablename__ = "production_batch_counters"

    day: Mapped[date] = mapped_column(Date, primary_key=True)
    last_number: Mapped[int] = mapped_column(Integer)
