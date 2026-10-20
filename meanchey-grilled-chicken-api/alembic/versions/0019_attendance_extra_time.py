"""attendance: early check-in and overtime

- `attendance_workplaces.count_early_checkin`, `count_overtime` (default true): whether early
  check-ins / overtime check-outs count as extra time at that workplace.
- `attendance_records.early_minutes`, `overtime_minutes` and the flags' snapshot `early_counts`,
  `overtime_counts`. Existing records are backfilled from their snapshot times, capped by their
  workplace's current open-before / check-out window (no workplace: 30 / 59 min); absent records
  and forgot check-outs get 0.

Revision ID: 0019
Revises: 0018
Create Date: 2026-10-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

W = "attendance_workplaces"
R = "attendance_records"


def _flag(name: str) -> sa.Column:
    return sa.Column(name, sa.Boolean(), nullable=False, server_default=sa.text("true"))


def _minutes(name: str) -> sa.Column:
    return sa.Column(name, sa.Integer(), nullable=False, server_default=sa.text("0"))


def upgrade() -> None:
    op.add_column(W, _flag("count_early_checkin"))
    op.add_column(W, _flag("count_overtime"))
    op.add_column(R, _minutes("early_minutes"))
    op.add_column(R, _minutes("overtime_minutes"))
    op.add_column(R, _flag("early_counts"))
    op.add_column(R, _flag("overtime_counts"))
    op.create_check_constraint(f"ck_{R}_early_minutes", R, "early_minutes >= 0")
    op.create_check_constraint(f"ck_{R}_overtime_minutes", R, "overtime_minutes >= 0")
    # Whole minutes, the check-in / check-out truncated to the minute (as people read them).
    op.execute(
        f"""
        UPDATE {R} r SET
          early_minutes = CASE WHEN r.check_in_at IS NOT NULL
              AND date_trunc('minute', r.check_in_at) < r.scheduled_start
            THEN LEAST(
              floor(extract(epoch FROM r.scheduled_start - date_trunc('minute', r.check_in_at))
                / 60)::int,
              COALESCE(w.open_before_min, 30))
            ELSE 0 END,
          overtime_minutes = CASE WHEN r.checkout_status = 'checked_out'
              AND r.check_out_at IS NOT NULL AND r.check_out_at > r.scheduled_end
            THEN LEAST(
              floor(extract(epoch FROM r.check_out_at - r.scheduled_end) / 60)::int,
              COALESCE(w.checkout_window_min, 59))
            ELSE 0 END
        FROM {R} r2 LEFT JOIN {W} w ON w.id = r2.workplace_id
        WHERE r2.id = r.id
        """
    )


def downgrade() -> None:
    op.drop_constraint(f"ck_{R}_overtime_minutes", R, type_="check")
    op.drop_constraint(f"ck_{R}_early_minutes", R, type_="check")
    for column in ("overtime_counts", "early_counts", "overtime_minutes", "early_minutes"):
        op.drop_column(R, column)
    op.drop_column(W, "count_overtime")
    op.drop_column(W, "count_early_checkin")
