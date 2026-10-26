"""attendance: per-employee schedule overrides and holiday work exceptions

- `attendance_employee_overrides`: an employee's own schedule versions (`user_id`,
  `effective_from`, unique together): `weekdays`, `shift_codes`, `shift_times` (each null =
  inherit the workplace's), `kept_shifts` (a version effective on its saving day: the shifts
  already open then, which keep the previous setting that day), `created_by` / `created_at`.
- `attendance_holiday_exceptions`: employees who work on a day of a holiday (`holiday_id`,
  `user_id`, `date`, unique together), with optional `shift_codes` / `shift_times`.

Nothing to backfill: without rows everyone follows their workplace as before. Three notification
types join the `notifications.type` CHECK: `attendance.schedule_changed`,
`attendance.holiday_work`, `attendance.holiday_off`.

Downgrade removes those notifications and drops both tables.

Revision ID: 0029
Revises: 0028
Create Date: 2026-10-26
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0029"
down_revision: str | None = "0028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

O = "attendance_employee_overrides"  # noqa: E741
E = "attendance_holiday_exceptions"
N = "notifications"
OLD_TYPES = (
    "production.processing_finished",
    "production.completed",
    "order.delivering",
    "order.delivered",
    "order.return_pending",
    "order.returns_reviewed",
    "preparation.finished",
    "attendance.request_submitted",
    "attendance.request_approved",
    "attendance.request_rejected",
    "attendance.request_reminder",
)
ADDED = ("attendance.schedule_changed", "attendance.holiday_work", "attendance.holiday_off")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def _created(table: str) -> list[Any]:
    return [
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name=f"fk_{table}_created_by_users", ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name=f"pk_{table}"),
    ]


def upgrade() -> None:
    op.create_table(
        O,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("weekdays", postgresql.ARRAY(sa.SmallInteger()), nullable=True),
        sa.Column("shift_codes", postgresql.ARRAY(sa.String(32)), nullable=True),
        sa.Column("shift_times", postgresql.JSONB(), nullable=True),
        sa.Column("kept_shifts", postgresql.JSONB(), nullable=True),
        *_created(O),
        sa.CheckConstraint(
            "weekdays IS NULL OR (cardinality(weekdays) BETWEEN 1 AND 7 "
            "AND weekdays <@ ARRAY[1, 2, 3, 4, 5, 6, 7]::smallint[])",
            name=f"ck_{O}_weekdays",
        ),
        sa.CheckConstraint(
            "shift_codes IS NULL OR cardinality(shift_codes) BETWEEN 1 AND 2",
            name=f"ck_{O}_shift_codes",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=f"fk_{O}_user", ondelete="CASCADE"),
        sa.UniqueConstraint("user_id", "effective_from", name=f"uq_{O}_date"),
    )
    op.create_table(
        E,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("holiday_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("shift_codes", postgresql.ARRAY(sa.String(32)), nullable=True),
        sa.Column("shift_times", postgresql.JSONB(), nullable=True),
        *_created(E),
        sa.CheckConstraint(
            "shift_codes IS NULL OR cardinality(shift_codes) BETWEEN 1 AND 2",
            name=f"ck_{E}_shift_codes",
        ),
        sa.ForeignKeyConstraint(
            ["holiday_id"], ["attendance_holidays.id"], name=f"fk_{E}_holiday", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=f"fk_{E}_user", ondelete="CASCADE"),
        sa.UniqueConstraint("holiday_id", "user_id", "date", name=f"uq_{E}_day"),
    )
    op.create_index(f"ix_{E}_user", E, ["user_id", "date"])
    op.drop_constraint(f"ck_{N}_type", N, type_="check")
    op.create_check_constraint(f"ck_{N}_type", N, _in("type", (*OLD_TYPES, *ADDED)))


def downgrade() -> None:
    op.execute(sa.text(f"DELETE FROM {N} WHERE {_in('type', ADDED)}"))
    op.drop_constraint(f"ck_{N}_type", N, type_="check")
    op.create_check_constraint(f"ck_{N}_type", N, _in("type", OLD_TYPES))
    op.drop_table(E)
    op.drop_table(O)
