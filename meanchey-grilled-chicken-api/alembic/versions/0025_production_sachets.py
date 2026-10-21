"""production step 3: satay sachets used (one per pack)

`production_packaging` gains `sachets_4_used` / `sachets_2_used` (int, null in drafts, >= 0) and
`sachets_4_manual` / `sachets_2_manual` (bool, default false: the value follows the pack count;
true once typed by hand). Backfill: every existing step 3 row gets its pack counts (big -> 4-piece,
small -> 2-piece) and manual = false, so finished rows show what they used and drafts start on
auto. No inventory movement is written for the past: only Finish from now on takes sachets.

Downgrade drops the columns (sachet movements already written stay in the ledger).

Revision ID: 0025
Revises: 0024
Create Date: 2026-10-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0025"
down_revision: str | None = "0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

T = "production_packaging"


def upgrade() -> None:
    op.add_column(T, sa.Column("sachets_4_used", sa.Integer(), nullable=True))
    op.add_column(T, sa.Column("sachets_2_used", sa.Integer(), nullable=True))
    for size in (4, 2):
        op.add_column(
            T,
            sa.Column(
                f"sachets_{size}_manual",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            ),
        )
    op.create_check_constraint(
        f"ck_{T}_sachets_nonnegative", T, "sachets_4_used >= 0 AND sachets_2_used >= 0"
    )
    op.execute(f"UPDATE {T} SET sachets_4_used = big_packages, sachets_2_used = small_packages")


def downgrade() -> None:
    op.drop_constraint(f"ck_{T}_sachets_nonnegative", T, type_="check")
    for column in ("sachets_2_manual", "sachets_4_manual", "sachets_2_used", "sachets_4_used"):
        op.drop_column(T, column)
