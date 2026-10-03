"""orders: orders, boxes, lines, returns, day counters; order stock movements; order alerts

- `orders`, `order_boxes`, `order_box_items`, `order_return_items`, `order_counters`.
- `inventory_movements.order_id` (the order a movement belongs to) and the `order` /
  `order_return` sources.
- Four notification types for the order alerts.

The wasted pack items need no migration (balance rows are created on demand and at startup);
the new permissions are registered and backfilled at startup (permissions/sync.py).

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ORDER_STATUSES = (
    "created",
    "delivering",
    "return_pending",
    "success",
    "partly_returned",
    "fully_returned",
    "cancelled",
)
OLD_TYPES = ("production.processing_finished", "production.completed")
NEW_TYPES = (
    *OLD_TYPES,
    "order.delivering",
    "order.delivered",
    "order.return_pending",
    "order.returns_reviewed",
)


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def _user_fk(t: str, column: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        [column], ["users.id"], name=f"fk_{t}_{column}_users", ondelete="SET NULL"
    )


def _ts(name: str, nullable: bool = True) -> sa.Column:
    if nullable:
        return sa.Column(name, sa.DateTime(timezone=True), nullable=True)
    return sa.Column(name, sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)


def upgrade() -> None:
    t = "order_counters"
    op.create_table(
        t,
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("last_number", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("day", name=f"pk_{t}"),
    )

    t = "orders"
    users = (
        "created_by",
        "updated_by",
        "delivering_by",
        "delivered_by",
        "returns_reviewed_by",
        "cancelled_by",
    )
    op.create_table(
        t,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.Column("customer_id", sa.Uuid(), nullable=False),
        sa.Column("delivery_date", sa.Date(), nullable=False),
        sa.Column("driver_id", sa.Uuid(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=16), server_default=sa.text("'created'"), nullable=False),
        sa.Column("return_reason", sa.String(length=500), nullable=True),
        sa.Column("cancel_reason", sa.String(length=500), nullable=True),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        *(sa.Column(c, sa.Uuid(), nullable=True) for c in users),
        _ts("created_at", nullable=False),
        _ts("updated_at", nullable=False),
        _ts("delivering_at"),
        _ts("delivered_at"),
        _ts("returns_reviewed_at"),
        _ts("cancelled_at"),
        sa.CheckConstraint(_in("status", ORDER_STATUSES), name=f"ck_{t}_status"),
        sa.CheckConstraint("char_length(note) <= 1000", name=f"ck_{t}_note_length"),
        sa.ForeignKeyConstraint(
            ["customer_id"], ["customers.id"], name=f"fk_{t}_customer_id_customers",
            ondelete="RESTRICT",
        ),
        _user_fk(t, "driver_id"),
        *(_user_fk(t, c) for c in users),
        sa.PrimaryKeyConstraint("id", name=f"pk_{t}"),
        sa.UniqueConstraint("code", name=f"uq_{t}_code"),
    )
    op.create_index("ix_orders_customer_id", t, ["customer_id"])
    op.create_index("ix_orders_driver_id", t, ["driver_id"])
    op.create_index("ix_orders_status_delivery_date", t, ["status", "delivery_date"])

    t = "order_boxes"
    op.create_table(
        t,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column("color", sa.String(length=16), nullable=False),
        sa.Column("position", sa.SmallInteger(), nullable=False),
        sa.CheckConstraint("color IN ('white', 'black')", name=f"ck_{t}_color"),
        sa.CheckConstraint("position >= 1", name=f"ck_{t}_position"),
        sa.ForeignKeyConstraint(
            ["order_id"], ["orders.id"], name=f"fk_{t}_order_id_orders", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=f"pk_{t}"),
        sa.UniqueConstraint("order_id", "position", name="uq_order_boxes_order_position"),
    )

    t = "order_box_items"
    op.create_table(
        t,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("box_id", sa.Uuid(), nullable=False),
        sa.Column("item_code", sa.String(length=64), nullable=False),
        sa.Column("count", sa.Integer(), nullable=True),
        sa.Column("kg", sa.Numeric(precision=12, scale=3), nullable=True),
        sa.Column("position", sa.SmallInteger(), server_default=sa.text("1"), nullable=False),
        sa.CheckConstraint(
            "(count IS NOT NULL AND kg IS NULL AND count > 0) "
            "OR (count IS NULL AND kg IS NOT NULL AND kg > 0)",
            name=f"ck_{t}_quantity",
        ),
        sa.ForeignKeyConstraint(
            ["box_id"], ["order_boxes.id"], name=f"fk_{t}_box_id_order_boxes", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=f"pk_{t}"),
        sa.UniqueConstraint("box_id", "item_code", name="uq_order_box_items_box_item"),
    )
    op.create_index("ix_order_box_items_box_id", t, ["box_id"])

    t = "order_return_items"
    op.create_table(
        t,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column("item_code", sa.String(length=64), nullable=False),
        sa.Column("returned_count", sa.Integer(), nullable=True),
        sa.Column("returned_kg", sa.Numeric(precision=12, scale=3), nullable=True),
        sa.Column("to_stock_count", sa.Integer(), nullable=True),
        sa.Column("to_stock_kg", sa.Numeric(precision=12, scale=3), nullable=True),
        sa.Column("to_wasted_count", sa.Integer(), nullable=True),
        sa.Column("to_wasted_kg", sa.Numeric(precision=12, scale=3), nullable=True),
        sa.Column("reviewed_by", sa.Uuid(), nullable=True),
        _ts("reviewed_at"),
        sa.CheckConstraint(
            "(returned_count IS NOT NULL AND returned_kg IS NULL AND returned_count > 0) "
            "OR (returned_count IS NULL AND returned_kg IS NOT NULL AND returned_kg > 0)",
            name=f"ck_{t}_returned",
        ),
        sa.CheckConstraint(
            "to_stock_count >= 0 AND to_wasted_count >= 0 AND to_stock_kg >= 0 "
            "AND to_wasted_kg >= 0",
            name=f"ck_{t}_split_nonnegative",
        ),
        sa.CheckConstraint(
            "reviewed_at IS NULL OR ("
            "COALESCE(to_stock_count, 0) + COALESCE(to_wasted_count, 0) "
            "= COALESCE(returned_count, 0) "
            "AND COALESCE(to_stock_kg, 0) + COALESCE(to_wasted_kg, 0) = COALESCE(returned_kg, 0))",
            name=f"ck_{t}_split_matches",
        ),
        sa.ForeignKeyConstraint(
            ["order_id"], ["orders.id"], name=f"fk_{t}_order_id_orders", ondelete="CASCADE"
        ),
        _user_fk(t, "reviewed_by"),
        sa.PrimaryKeyConstraint("id", name=f"pk_{t}"),
        sa.UniqueConstraint("order_id", "item_code", name="uq_order_return_items_order_item"),
    )
    op.create_index("ix_order_return_items_order_id", t, ["order_id"])

    t = "inventory_movements"
    op.add_column(t, sa.Column("order_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        f"fk_{t}_order_id_orders", t, "orders", ["order_id"], ["id"], ondelete="SET NULL"
    )
    op.create_index("ix_inventory_movements_order_id", t, ["order_id"])
    op.drop_constraint(f"ck_{t}_source", t, type_="check")
    op.create_check_constraint(
        f"ck_{t}_source", t, "source IN ('production', 'adjustment', 'order', 'order_return')"
    )

    t = "notifications"
    op.drop_constraint(f"ck_{t}_type", t, type_="check")
    op.create_check_constraint(f"ck_{t}_type", t, _in("type", NEW_TYPES))


def downgrade() -> None:
    t = "notifications"
    op.execute(f"DELETE FROM {t} WHERE type LIKE 'order.%'")
    op.drop_constraint(f"ck_{t}_type", t, type_="check")
    op.create_check_constraint(f"ck_{t}_type", t, _in("type", OLD_TYPES))

    t = "inventory_movements"
    # Order movements can't exist without orders; a downgrade drops them (stock is not restored).
    op.execute(f"DELETE FROM {t} WHERE source IN ('order', 'order_return')")
    op.drop_constraint(f"ck_{t}_source", t, type_="check")
    op.create_check_constraint(f"ck_{t}_source", t, "source IN ('production', 'adjustment')")
    op.drop_index("ix_inventory_movements_order_id", table_name=t)
    op.drop_constraint(f"fk_{t}_order_id_orders", t, type_="foreignkey")
    op.drop_column(t, "order_id")

    op.drop_table("order_return_items")
    op.drop_table("order_box_items")
    op.drop_table("order_boxes")
    op.drop_table("orders")
    op.drop_table("order_counters")
