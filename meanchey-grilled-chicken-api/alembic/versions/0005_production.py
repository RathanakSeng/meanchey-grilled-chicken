"""production batches (raw material, produced, standardize) + by-products + day counters

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

KG = sa.Numeric(10, 3)
GRAMS = sa.Numeric(10, 1)


def _user_fk(table: str, column: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        [column], ["users.id"], name=f"fk_{table}_{column}_users", ondelete="SET NULL"
    )


def _batch_fk(table: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["batch_id"],
        ["production_batches.id"],
        name=f"fk_{table}_batch_id_production_batches",
        ondelete="CASCADE",
    )


def _step_columns() -> list[sa.Column]:
    return [
        sa.Column("status", sa.String(length=16), server_default=sa.text("'draft'"), nullable=False),
        sa.Column("finished_by", sa.Uuid(), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    ]


def _step_constraints(table: str) -> list[sa.Constraint]:
    return [
        sa.CheckConstraint("status IN ('draft', 'finished')", name=f"ck_{table}_status"),
        _user_fk(table, "finished_by"),
        _user_fk(table, "updated_by"),
        _batch_fk(table),
        sa.PrimaryKeyConstraint("batch_id", name=f"pk_{table}"),
    ]


def upgrade() -> None:
    t = "production_batches"
    op.create_table(
        t,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.Column("production_date", sa.Date(), nullable=False),
        sa.Column(
            "status", sa.String(length=16), server_default=sa.text("'in_progress'"), nullable=False
        ),
        sa.Column("current_step", sa.SmallInteger(), server_default=sa.text("1"), nullable=False),
        sa.Column("cancel_reason", sa.String(length=500), nullable=True),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.Column("cancelled_by", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('in_progress', 'completed', 'cancelled')", name=f"ck_{t}_status"
        ),
        sa.CheckConstraint("current_step BETWEEN 1 AND 3", name=f"ck_{t}_current_step"),
        _user_fk(t, "created_by"),
        _user_fk(t, "updated_by"),
        _user_fk(t, "cancelled_by"),
        sa.PrimaryKeyConstraint("id", name=f"pk_{t}"),
        sa.UniqueConstraint("code", name=f"uq_{t}_code"),
    )
    op.create_index("ix_production_batches_production_date", t, ["production_date"])
    op.create_index("ix_production_batches_status_step", t, ["status", "current_step"])

    t = "production_raw_materials"
    op.create_table(
        t,
        sa.Column("batch_id", sa.Uuid(), nullable=False),
        sa.Column("supplier_id", sa.Uuid(), nullable=True),
        sa.Column("material_kind", sa.String(length=32), nullable=False),
        sa.Column("weight_kg", KG, nullable=True),
        sa.Column("quantity", sa.Integer(), nullable=True),
        *_step_columns(),
        sa.CheckConstraint("weight_kg >= 0", name=f"ck_{t}_weight_kg"),
        sa.CheckConstraint("quantity >= 0", name=f"ck_{t}_quantity"),
        sa.ForeignKeyConstraint(
            ["supplier_id"],
            ["suppliers.id"],
            name=f"fk_{t}_supplier_id_suppliers",
            ondelete="RESTRICT",
        ),
        *_step_constraints(t),
    )
    op.create_index("ix_production_raw_materials_supplier_id", t, ["supplier_id"])

    t = "production_outputs"
    op.create_table(
        t,
        sa.Column("batch_id", sa.Uuid(), nullable=False),
        sa.Column("wings_kg", KG, nullable=True),
        sa.Column("thighs_kg", KG, nullable=True),
        sa.Column("wings_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("thighs_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("marinade_g", GRAMS, nullable=True),
        *_step_columns(),
        sa.CheckConstraint(
            "wings_kg >= 0 AND thighs_kg >= 0 AND marinade_g >= 0", name=f"ck_{t}_nonnegative"
        ),
        *_step_constraints(t),
    )

    t = "production_packaging"
    op.create_table(
        t,
        sa.Column("batch_id", sa.Uuid(), nullable=False),
        sa.Column("big_packages", sa.Integer(), nullable=True),
        sa.Column("small_packages", sa.Integer(), nullable=True),
        sa.Column("rejected_wings", sa.Integer(), nullable=True),
        sa.Column("rejected_thighs", sa.Integer(), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        *_step_columns(),
        sa.CheckConstraint(
            "big_packages >= 0 AND small_packages >= 0 "
            "AND rejected_wings >= 0 AND rejected_thighs >= 0",
            name=f"ck_{t}_nonnegative",
        ),
        *_step_constraints(t),
    )

    t = "production_byproducts"
    op.create_table(
        t,
        sa.Column("batch_id", sa.Uuid(), nullable=False),
        sa.Column("item_code", sa.String(length=32), nullable=False),
        sa.Column("produced_kg", KG, nullable=True),
        sa.Column("carry_kg", KG, nullable=True),
        sa.Column("rejected_kg", KG, nullable=True),
        sa.CheckConstraint(
            "produced_kg >= 0 AND carry_kg >= 0 AND rejected_kg >= 0", name=f"ck_{t}_nonnegative"
        ),
        _batch_fk(t),
        sa.PrimaryKeyConstraint("batch_id", "item_code", name=f"pk_{t}"),
    )

    op.create_table(
        "production_batch_counters",
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("last_number", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("day", name="pk_production_batch_counters"),
    )


def downgrade() -> None:
    op.drop_table("production_batch_counters")
    op.drop_table("production_byproducts")
    op.drop_table("production_packaging")
    op.drop_table("production_outputs")
    op.drop_index("ix_production_raw_materials_supplier_id", table_name="production_raw_materials")
    op.drop_table("production_raw_materials")
    op.drop_index("ix_production_batches_status_step", table_name="production_batches")
    op.drop_index("ix_production_batches_production_date", table_name="production_batches")
    op.drop_table("production_batches")
