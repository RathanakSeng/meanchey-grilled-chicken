"""attendance: alerts to general managers (check-ins, check-outs, absent / forgot check-out)

- Notification types `attendance.checked_in`, `attendance.checked_out` (one per event,
  `entity_type = attendance_record`) and `attendance.shift_absent`,
  `attendance.shift_forgot_checkout` (one per workplace / date / shift / cutoff,
  `entity_type = attendance_shift`).

The permission `attendance.checkin_alerts` needs nothing here: the registry sync inserts it at
startup and grants it once to existing active general managers (a GM default). Downgrade deletes
these notifications.

Revision ID: 0031
Revises: 0030
Create Date: 2026-11-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0031"
down_revision: str | None = "0030"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

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
    "attendance.schedule_changed",
    "attendance.holiday_work",
    "attendance.holiday_off",
    "inventory.cleared",
)
NEW_TYPES = (
    "attendance.checked_in",
    "attendance.checked_out",
    "attendance.shift_absent",
    "attendance.shift_forgot_checkout",
)


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def upgrade() -> None:
    op.drop_constraint(f"ck_{N}_type", N, type_="check")
    op.create_check_constraint(f"ck_{N}_type", N, _in("type", (*OLD_TYPES, *NEW_TYPES)))


def downgrade() -> None:
    op.execute(
        sa.text(f"DELETE FROM {N} WHERE type IN ({', '.join(repr(t) for t in NEW_TYPES)})")
    )
    op.drop_constraint(f"ck_{N}_type", N, type_="check")
    op.create_check_constraint(f"ck_{N}_type", N, _in("type", OLD_TYPES))
