"""inventory: clear stock (CL-YYYYMMDD-NNN)

- `inventory_clears`: one clear (`code` unique, `reason`, `impacts_snapshot` = the impacts that
  were acknowledged, `created_by` / `created_at`).
- `inventory_clear_lines`: per item, the quantity taken out (`count` / `kg` / `g` / `m2`,
  `kg_estimated`) and `moved_to_item_code` (its wasted item, null: removed).
- `inventory_clear_counters`: the last number per day.
- `inventory_movements.clear_id` (FK, SET NULL) and the movement source `clear`.
- Notification type `inventory.cleared`.

Nothing to backfill. Downgrade refuses while clears exist (their movements would be left
unexplained), otherwise drops everything.

Revision ID: 0030
Revises: 0029
Create Date: 2026-10-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0030"
down_revision: str | None = "0029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

C = "inventory_clears"
L = "inventory_clear_lines"
K = "inventory_clear_counters"
M = "inventory_movements"
N = "notifications"
OLD_SOURCES = (
    "production",
    "adjustment",
    "order",
    "order_return",
    "material_add",
    "material_remove",
    "material_unit_change",
    "preparation",
)
OLD_TYPES = (
    "production.processing_finished",
    "production.completed",
    "order.delivering",
    "order.delivered",
    "order.return_pending",
    "order.returns_reviewed",
    "preparation.finished",
    "attendance.request_submitted",
    "attendance.request_approved",
    "attendance.request_rejected",
    "attendance.request_reminder",
    "attendance.schedule_changed",
    "attendance.holiday_work",
    "attendance.holiday_off",
)


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def upgrade() -> None:
    op.create_table(
        C,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(32), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "impacts_snapshot",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("char_length(reason) BETWEEN 1 AND 500", name=f"ck_{C}_reason"),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name=f"fk_{C}_created_by_users", ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name=f"pk_{C}"),
        sa.UniqueConstraint("code", name=f"uq_{C}_code"),
    )
    op.create_index(f"ix_{C}_created_at", C, ["created_at"])
    op.create_table(
        L,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("clear_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.SmallInteger(), nullable=False),
        sa.Column("item_code", sa.String(64), nullable=False),
        sa.Column("count", sa.Integer(), nullable=True),
        sa.Column("kg", sa.Numeric(12, 3), nullable=True),
        sa.Column("g", sa.Numeric(14, 1), nullable=True),
        sa.Column("m2", sa.Numeric(14, 2), nullable=True),
        sa.Column("kg_estimated", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("moved_to_item_code", sa.String(64), nullable=True),
        sa.CheckConstraint(
            "count IS NOT NULL OR kg IS NOT NULL OR g IS NOT NULL OR m2 IS NOT NULL",
            name=f"ck_{L}_has_quantity",
        ),
        sa.CheckConstraint("count >= 0 AND kg >= 0 AND g >= 0 AND m2 >= 0", name=f"ck_{L}_quantity"),
        sa.ForeignKeyConstraint(
            ["clear_id"], [f"{C}.id"], name=f"fk_{L}_clear_id_{C}", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=f"pk_{L}"),
    )
    op.create_index(f"ix_{L}_clear_id", L, ["clear_id"])
    op.create_table(
        K,
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("last_number", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("day", name=f"pk_{K}"),
    )
    op.add_column(M, sa.Column("clear_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(f"fk_{M}_clear_id_{C}", M, C, ["clear_id"], ["id"], ondelete="SET NULL")
    op.create_index(f"ix_{M}_clear_id", M, ["clear_id"])
    op.drop_constraint(f"ck_{M}_source", M, type_="check")
    op.create_check_constraint(f"ck_{M}_source", M, _in("source", (*OLD_SOURCES, "clear")))
    op.drop_constraint(f"ck_{N}_type", N, type_="check")
    op.create_check_constraint(f"ck_{N}_type", N, _in("type", (*OLD_TYPES, "inventory.cleared")))


def downgrade() -> None:
    # Clears moved stock: dropping them would leave movements and balances nobody can explain.
    count = op.get_bind().scalar(sa.text(f"SELECT count(*) FROM {C}"))
    if count:
        raise RuntimeError(f"{count} clear(s) exist; they can't be downgraded")
    op.execute(sa.text(f"DELETE FROM {N} WHERE type = 'inventory.cleared'"))
    op.drop_constraint(f"ck_{N}_type", N, type_="check")
    op.create_check_constraint(f"ck_{N}_type", N, _in("type", OLD_TYPES))
    op.drop_constraint(f"ck_{M}_source", M, type_="check")
    op.create_check_constraint(f"ck_{M}_source", M, _in("source", OLD_SOURCES))
    op.drop_index(f"ix_{M}_clear_id", table_name=M)
    op.drop_constraint(f"fk_{M}_clear_id_{C}", M, type_="foreignkey")
    op.drop_column(M, "clear_id")
    op.drop_table(K)
    op.drop_table(L)
    op.drop_table(C)
