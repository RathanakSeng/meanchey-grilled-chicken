"""attendance: no GPS accuracy rule

Check-in / check-out only checks the distance to the workplace; the phone's GPS accuracy is still
stored with each record but never refuses one. `attendance_schedule_versions.max_accuracy_m` and
its CHECK are dropped.

Downgrade adds the column back with 100 m (the old default) in every version.

Revision ID: 0027
Revises: 0026
Create Date: 2026-10-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0027"
down_revision: str | None = "0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

T = "attendance_schedule_versions"


def upgrade() -> None:
    # Dropping the column drops its CHECK too.
    op.drop_column(T, "max_accuracy_m")


def downgrade() -> None:
    op.add_column(
        T, sa.Column("max_accuracy_m", sa.Integer(), server_default="100", nullable=False)
    )
    op.alter_column(T, "max_accuracy_m", server_default=None)
    op.create_check_constraint(f"ck_{T}_max_accuracy", T, "max_accuracy_m BETWEEN 10 AND 500")
