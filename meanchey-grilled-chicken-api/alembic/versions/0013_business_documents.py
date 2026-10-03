"""business info and delivery notes: business_settings (one row), orders.print_count

- `business_settings`: what documents print at the top and bottom (names, address, phone, footer
  note, logo). Seeded with the business name only.
- `orders.print_count`: delivery notes generated so far (later ones are marked COPY).

The `settings.business_info` permission is registered at startup (permissions/sync.py).

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    t = "business_settings"
    op.create_table(
        t,
        sa.Column("id", sa.SmallInteger(), nullable=False),
        sa.Column("name_km", sa.String(200), nullable=False),
        sa.Column("name_en", sa.String(200), nullable=False),
        sa.Column("address_km", sa.String(500), nullable=True),
        sa.Column("address_en", sa.String(500), nullable=True),
        sa.Column("phone", sa.String(32), nullable=True),
        sa.Column("footer_note_km", sa.String(300), nullable=True),
        sa.Column("footer_note_en", sa.String(300), nullable=True),
        sa.Column("logo", sa.LargeBinary(), nullable=True),
        sa.Column("logo_mime", sa.String(16), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("id = 1", name=f"ck_{t}_single_row"),
        sa.CheckConstraint("(logo IS NULL) = (logo_mime IS NULL)", name=f"ck_{t}_logo_mime"),
        sa.ForeignKeyConstraint(
            ["updated_by"], ["users.id"], name=f"fk_{t}_updated_by_users", ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name=f"pk_{t}"),
    )
    op.execute(
        "INSERT INTO business_settings (id, name_km, name_en) "
        "VALUES (1, 'មាន់អាំងមានជ័យ', 'Mean Chey Grilled Chicken')"
    )
    op.add_column(
        "orders",
        sa.Column("print_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("orders", "print_count")
    op.drop_table("business_settings")
