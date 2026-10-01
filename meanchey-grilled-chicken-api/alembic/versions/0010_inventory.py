"""inventory: balances, movements ledger, tracked batches

- `inventory_balances`: one row per catalog item (created on demand and at startup; none here).
- `inventory_movements`: append-only ledger; a movement is reversed at most once (unique partial
  index on `reversal_of`).
- `production_batches.inventory_tracked`: false for every existing batch, so inventory starts at
  zero and stays consistent (their finish / reopen / cancel never write movements); true for new
  batches.

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    t = "inventory_balances"
    op.create_table(
        t,
        sa.Column("item_code", sa.String(length=64), nullable=False),
        sa.Column("count", sa.Integer(), nullable=True),
        sa.Column("kg", sa.Numeric(precision=12, scale=3), nullable=True),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("count >= 0", name=f"ck_{t}_count"),
        sa.CheckConstraint("kg >= 0", name=f"ck_{t}_kg"),
        sa.PrimaryKeyConstraint("item_code", name=f"pk_{t}"),
    )

    t = "inventory_movements"
    op.create_table(
        t,
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("item_code", sa.String(length=64), nullable=False),
        sa.Column("count_delta", sa.Integer(), nullable=True),
        sa.Column("kg_delta", sa.Numeric(precision=12, scale=3), nullable=True),
        sa.Column("kg_estimated", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("batch_id", sa.Uuid(), nullable=True),
        sa.Column("step", sa.SmallInteger(), nullable=True),
        sa.Column("reversal_of", sa.BigInteger(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("balance_count_after", sa.Integer(), nullable=True),
        sa.Column("balance_kg_after", sa.Numeric(precision=12, scale=3), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("source IN ('production', 'adjustment')", name=f"ck_{t}_source"),
        sa.CheckConstraint("step IS NULL OR step BETWEEN 1 AND 3", name=f"ck_{t}_step"),
        sa.CheckConstraint(
            "count_delta IS NOT NULL OR kg_delta IS NOT NULL", name=f"ck_{t}_has_delta"
        ),
        sa.ForeignKeyConstraint(
            ["batch_id"],
            ["production_batches.id"],
            name=f"fk_{t}_batch_id_production_batches",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["reversal_of"],
            [f"{t}.id"],
            name=f"fk_{t}_reversal_of_{t}",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name=f"fk_{t}_created_by_users", ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name=f"pk_{t}"),
    )
    op.create_index("ix_inventory_movements_item_created", t, ["item_code", "created_at"])
    op.create_index("ix_inventory_movements_batch_id", t, ["batch_id"])
    op.create_index(
        "uq_inventory_movements_reversal_of",
        t,
        ["reversal_of"],
        unique=True,
        postgresql_where=sa.text("reversal_of IS NOT NULL"),
    )

    # Existing batches: not tracked. New batches: tracked (the default switches afterwards).
    op.add_column(
        "production_batches",
        sa.Column(
            "inventory_tracked", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
    )
    op.alter_column("production_batches", "inventory_tracked", server_default=sa.text("true"))


def downgrade() -> None:
    op.drop_column("production_batches", "inventory_tracked")
    op.drop_table("inventory_movements")
    op.drop_table("inventory_balances")
