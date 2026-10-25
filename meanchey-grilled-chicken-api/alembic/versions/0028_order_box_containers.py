"""order boxes: returnable containers

`order_boxes` gains `returnable` (bool, not null: the container must come back from the customer)
and the container's result: `container_status` (`pending` | `returned` | `not_returned`, null when
not returnable), `container_reason` (<= 300, required for not_returned), `container_recorded_by` /
`_at` (at Delivered) and `container_returned_later_by` / `_at` (marked returned afterwards).

Backfill: boxes of Created / Delivering orders get the type default (white and black boxes
returnable, plastic bags and delivery bags not) and `pending` when returnable; boxes of finished or
cancelled orders get `returnable = false` (no history to invent).

Downgrade drops the columns.

Revision ID: 0028
Revises: 0027
Create Date: 2026-10-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0028"
down_revision: str | None = "0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

T = "order_boxes"
CHECKS = {
    "container_status": "container_status IN ('pending', 'returned', 'not_returned')",
    "container_returnable": "returnable OR container_status IS NULL",
    "container_reason": (
        "container_status IS DISTINCT FROM 'not_returned' OR container_reason IS NOT NULL"
    ),
    "container_reason_length": "char_length(container_reason) <= 300",
}
USER_COLUMNS = ("container_recorded_by", "container_returned_later_by")


def upgrade() -> None:
    op.add_column(
        T, sa.Column("returnable", sa.Boolean(), nullable=False, server_default=sa.text("false"))
    )
    op.add_column(T, sa.Column("container_status", sa.String(16), nullable=True))
    op.add_column(T, sa.Column("container_reason", sa.String(300), nullable=True))
    for column in USER_COLUMNS:
        op.add_column(T, sa.Column(column, sa.Uuid(), nullable=True))
        op.create_foreign_key(
            f"fk_{T}_{column}_users", T, "users", [column], ["id"], ondelete="SET NULL"
        )
    op.add_column(T, sa.Column("container_recorded_at", sa.DateTime(timezone=True)))
    op.add_column(T, sa.Column("container_returned_later_at", sa.DateTime(timezone=True)))
    for name, condition in CHECKS.items():
        op.create_check_constraint(f"ck_{T}_{name}", T, condition)
    # The defaults per type (models/order.py BOX_RETURNABLE), only for orders not yet delivered.
    op.execute(
        f"UPDATE {T} b SET returnable = true, container_status = 'pending' FROM orders o "
        "WHERE o.id = b.order_id AND o.status IN ('created', 'delivering') "
        "AND b.color IN ('white', 'black')"
    )
    # Set explicitly on every insert from now on.
    op.alter_column(T, "returnable", server_default=None)


def downgrade() -> None:
    for name in CHECKS:
        op.drop_constraint(f"ck_{T}_{name}", T, type_="check")
    for column in USER_COLUMNS:
        op.drop_constraint(f"fk_{T}_{column}_users", T, type_="foreignkey")
    for column in (
        "container_returned_later_at",
        "container_returned_later_by",
        "container_recorded_at",
        "container_recorded_by",
        "container_reason",
        "container_status",
        "returnable",
    ):
        op.drop_column(T, column)
