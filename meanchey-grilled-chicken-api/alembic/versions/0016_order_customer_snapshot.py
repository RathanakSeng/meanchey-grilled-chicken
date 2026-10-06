"""order customer: saved customer or direct order, with the customer details snapshotted

- `customer_type`: `saved` (a customer from Customers) or `direct` (no saved customer; a phone
  and an optional location entered for this order only).
- `customer_id` becomes nullable (null for direct orders).
- `customer_name` / `customer_phone` / `customer_location`: what the order shows, refreshed while
  the order is Created and frozen from Delivering on.
- Existing orders: `saved`, snapshot from their customer's current name, phone and location.

Revision ID: 0016
Revises: 0015
Create Date: 2026-10-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

T = "orders"


def upgrade() -> None:
    op.add_column(T, sa.Column("customer_type", sa.String(16), nullable=True))
    op.add_column(T, sa.Column("customer_name", sa.String(150), nullable=True))
    op.add_column(T, sa.Column("customer_phone", sa.String(20), nullable=True))
    op.add_column(T, sa.Column("customer_location", sa.String(255), nullable=True))
    op.execute(
        "UPDATE orders AS o SET customer_type = 'saved', customer_name = c.name, "
        "customer_phone = c.phone, customer_location = c.location "
        "FROM customers AS c WHERE c.id = o.customer_id"
    )
    op.alter_column(T, "customer_type", nullable=False)
    op.alter_column(T, "customer_id", nullable=True)
    op.create_check_constraint(
        f"ck_{T}_customer_type", T, "customer_type IN ('saved', 'direct')"
    )
    op.create_check_constraint(
        f"ck_{T}_customer",
        T,
        "(customer_type = 'saved' AND customer_id IS NOT NULL) OR "
        "(customer_type = 'direct' AND customer_id IS NULL AND customer_phone IS NOT NULL)",
    )


def downgrade() -> None:
    # Direct orders have no customer to point back to; never drop them (stock movements reference
    # them). Refuse instead.
    direct = op.get_bind().scalar(sa.text("SELECT count(*) FROM orders WHERE customer_type = 'direct'"))
    if direct:
        raise RuntimeError(f"{direct} direct order(s) exist; they can't be downgraded")
    op.drop_constraint(f"ck_{T}_customer", T, type_="check")
    op.drop_constraint(f"ck_{T}_customer_type", T, type_="check")
    op.alter_column(T, "customer_id", nullable=False)
    op.drop_column(T, "customer_location")
    op.drop_column(T, "customer_phone")
    op.drop_column(T, "customer_name")
    op.drop_column(T, "customer_type")
