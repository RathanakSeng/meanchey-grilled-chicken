"""production step dates recorded at Finish; drop the batch-level production date

Each step table gets its own date (import / production / packaging), set by the server when the
step is finished and cleared when it is reopened. Existing finished steps take the date of their
`finished_at` in BUSINESS_TIMEZONE; drafts stay null. Batch codes are not touched.

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.config import get_settings

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (table, date column)
STEP_DATES = (
    ("production_raw_materials", "import_date"),
    ("production_outputs", "production_date"),
    ("production_packaging", "packaging_date"),
)


def upgrade() -> None:
    tz = get_settings().business_timezone
    for table, column in STEP_DATES:
        op.add_column(table, sa.Column(column, sa.Date(), nullable=True))
        op.execute(
            sa.text(
                f"UPDATE {table} SET {column} = (finished_at AT TIME ZONE :tz)::date "
                "WHERE status = 'finished'"
            ).bindparams(tz=tz)
        )
        # A finished step always has its date; a draft never has one.
        op.create_check_constraint(
            op.f(f"ck_{table}_{column}_matches_status"),
            table,
            f"(status = 'finished') = ({column} IS NOT NULL)",
        )
        op.create_index(f"ix_{table}_{column}", table, [column])

    op.drop_index("ix_production_batches_production_date", table_name="production_batches")
    op.drop_column("production_batches", "production_date")


def downgrade() -> None:
    tz = get_settings().business_timezone
    op.add_column("production_batches", sa.Column("production_date", sa.Date(), nullable=True))
    op.execute(
        sa.text(
            "UPDATE production_batches b SET production_date = COALESCE("
            "(SELECT r.import_date FROM production_raw_materials r WHERE r.batch_id = b.id), "
            "(b.created_at AT TIME ZONE :tz)::date)"
        ).bindparams(tz=tz)
    )
    op.alter_column("production_batches", "production_date", nullable=False)
    op.create_index(
        "ix_production_batches_production_date", "production_batches", ["production_date"]
    )
    for table, column in STEP_DATES:
        op.drop_index(f"ix_{table}_{column}", table_name=table)
        op.drop_constraint(op.f(f"ck_{table}_{column}_matches_status"), table, type_="check")
        op.drop_column(table, column)
