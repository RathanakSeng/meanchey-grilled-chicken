"""attendance start date and optional tracking for supervisors

- `users.attendance_start_date` (date, nullable): the first day attendance is tracked for a staff
  member or supervisor; backfilled with the date of `created_at` in the business time zone.
  Null for general managers and the superadmin.
- `users.attendance_tracked` (bool, default true): staff are always tracked; a supervisor can be
  switched off.
- `attendance_untracked_periods`: the history of switching a supervisor's tracking off
  (`to_date` null = ongoing).

Downgrade drops the table and both columns.

Revision ID: 0021
Revises: 0020
Create Date: 2026-10-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.config import get_settings

revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

T = "attendance_untracked_periods"


def upgrade() -> None:
    op.add_column("users", sa.Column("attendance_start_date", sa.Date(), nullable=True))
    op.add_column(
        "users",
        sa.Column(
            "attendance_tracked", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
    )
    zone = get_settings().business_timezone
    op.execute(
        sa.text(
            "UPDATE users SET attendance_start_date = (created_at AT TIME ZONE :zone)::date "
            "WHERE role IN ('staff', 'supervisor')"
        ).bindparams(zone=zone)
    )
    op.create_table(
        T,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("from_date", sa.Date(), nullable=False),
        sa.Column("to_date", sa.Date(), nullable=True),
        sa.Column("set_by", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("to_date IS NULL OR to_date >= from_date", name=f"ck_{T}_range"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=f"fk_{T}_user_id_users", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["set_by"], ["users.id"], name=f"fk_{T}_set_by_users", ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name=f"pk_{T}"),
    )
    op.create_index(f"ix_{T}_user", T, ["user_id", "from_date"])
    # At most one ongoing period per user.
    op.create_index(
        f"uq_{T}_open", T, ["user_id"], unique=True, postgresql_where=sa.text("to_date IS NULL")
    )


def downgrade() -> None:
    op.drop_table(T)
    op.drop_column("users", "attendance_tracked")
    op.drop_column("users", "attendance_start_date")
