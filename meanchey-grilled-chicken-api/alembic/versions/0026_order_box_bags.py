"""order boxes: plastic bags and delivery bags

`order_boxes.color` accepts two more containers besides the white and black boxes:
`plastic_bag` and `delivery_bag` (the CHECK `ck_order_boxes_color` is recreated).

Downgrade puts the old CHECK back; it fails while any order still has a bag (change or remove
those boxes first).

Revision ID: 0026
Revises: 0025
Create Date: 2026-10-21
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0026"
down_revision: str | None = "0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

T = "order_boxes"
NAME = f"ck_{T}_color"


def upgrade() -> None:
    op.drop_constraint(NAME, T, type_="check")
    op.create_check_constraint(
        NAME, T, "color IN ('white', 'black', 'plastic_bag', 'delivery_bag')"
    )


def downgrade() -> None:
    op.drop_constraint(NAME, T, type_="check")
    op.create_check_constraint(NAME, T, "color IN ('white', 'black')")
