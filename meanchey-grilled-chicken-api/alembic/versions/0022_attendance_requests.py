"""attendance requests: monthly missing-time requests (salary cut / unpaid extra work)

- `attendance_requests`: one per employee and month (unique), with the month's figures
  snapshotted, the requested and approved splits, the review and the type.
- Notification types `attendance.request_submitted`, `attendance.request_approved`,
  `attendance.request_rejected`, `attendance.request_reminder`.

The deadline setting (`request_deadline_day`, default 7) lives in `app_settings`; no row is
needed until the superadmin changes it. Downgrade drops the table and removes those notifications.

Revision ID: 0022
Revises: 0021
Create Date: 2026-10-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

T = "attendance_requests"
OLD_TYPES = (
    "production.processing_finished",
    "production.completed",
    "order.delivering",
    "order.delivered",
    "order.return_pending",
    "order.returns_reviewed",
    "preparation.finished",
)
NEW_TYPES = (
    *OLD_TYPES,
    "attendance.request_submitted",
    "attendance.request_approved",
    "attendance.request_rejected",
    "attendance.request_reminder",
)


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def upgrade() -> None:
    op.create_table(
        T,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("year", sa.SmallInteger(), nullable=False),
        sa.Column("month", sa.SmallInteger(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("missing_minutes", sa.Integer(), nullable=False),
        sa.Column("extra_minutes", sa.Integer(), nullable=False),
        sa.Column("absent_minutes", sa.Integer(), nullable=False),
        sa.Column("late_minutes", sa.Integer(), nullable=False),
        sa.Column("balance_minutes", sa.Integer(), nullable=False),
        sa.Column("requested_salary_cut_minutes", sa.Integer(), nullable=False),
        sa.Column("requested_unpaid_work_minutes", sa.Integer(), nullable=False),
        sa.Column("approved_salary_cut_minutes", sa.Integer(), nullable=True),
        sa.Column("approved_unpaid_work_minutes", sa.Integer(), nullable=True),
        sa.Column("type", sa.String(16), nullable=False),
        sa.Column(
            "approved_with_changes", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column("note", sa.String(500), nullable=True),
        sa.Column("review_comment", sa.String(500), nullable=True),
        sa.Column("reject_reason", sa.String(500), nullable=True),
        sa.Column(
            "submitted_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("reviewed_by", sa.Uuid(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            _in("status", ("pending", "approved", "rejected")), name=f"ck_{T}_status"
        ),
        sa.CheckConstraint(
            _in("type", ("salary_cut", "unpaid_work", "both")), name=f"ck_{T}_type"
        ),
        sa.CheckConstraint("month BETWEEN 1 AND 12", name=f"ck_{T}_month"),
        sa.CheckConstraint(
            "requested_salary_cut_minutes >= 0 AND requested_unpaid_work_minutes >= 0 "
            "AND requested_salary_cut_minutes + requested_unpaid_work_minutes = missing_minutes",
            name=f"ck_{T}_requested_split",
        ),
        sa.CheckConstraint(
            "(approved_salary_cut_minutes IS NULL) = (approved_unpaid_work_minutes IS NULL) "
            "AND (approved_salary_cut_minutes IS NULL OR (approved_salary_cut_minutes >= 0 "
            "AND approved_unpaid_work_minutes >= 0 AND approved_salary_cut_minutes "
            "+ approved_unpaid_work_minutes = missing_minutes))",
            name=f"ck_{T}_approved_split",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=f"fk_{T}_user_id_users", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["reviewed_by"], ["users.id"], name=f"fk_{T}_reviewed_by_users", ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name=f"pk_{T}"),
        sa.UniqueConstraint("user_id", "year", "month", name=f"uq_{T}_month"),
    )
    op.create_index(f"ix_{T}_status", T, ["status", "submitted_at"])
    op.create_index(f"ix_{T}_month", T, ["year", "month"])

    n = "notifications"
    op.drop_constraint(f"ck_{n}_type", n, type_="check")
    op.create_check_constraint(f"ck_{n}_type", n, _in("type", NEW_TYPES))


def downgrade() -> None:
    n = "notifications"
    op.execute(f"DELETE FROM {n} WHERE type LIKE 'attendance.request_%'")
    op.drop_constraint(f"ck_{n}_type", n, type_="check")
    op.create_check_constraint(f"ck_{n}_type", n, _in("type", OLD_TYPES))
    op.drop_table(T)
