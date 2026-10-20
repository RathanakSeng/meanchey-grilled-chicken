"""attendance: workplaces (with their rules), shifts per workplace, records, reminders;
users.workplace_id

- `attendance_workplaces` (one default, seeded "Mean Chey" without coordinates: check-in is
  refused until the superadmin sets them), each with its rules (30 / 45 / 59 min, accuracy
  100 m, reminders on) and its own `attendance_shifts` (morning 07:00–12:00, afternoon
  13:00–15:00).
- `attendance_records` (one per user, day and shift; shift times snapshotted) and
  `attendance_reminders` (each reminder once).
- `users.workplace_id`: every staff member and supervisor (active or not) gets the default
  workplace.

Revision ID: 0018
Revises: 0017
Create Date: 2026-10-13
"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SHIFT_CODES = ("morning", "afternoon")
REMINDER_STATUSES = ("pending", "sending", "sent", "failed", "not_linked", "bot_off", "skipped")
DEFAULT_WORKPLACE_NAME = "Mean Chey"


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def _user_fk(t: str, column: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        [column], ["users.id"], name=f"fk_{t}_{column}_users", ondelete="SET NULL"
    )


def _ts(name: str, nullable: bool = True) -> sa.Column:
    if nullable:
        return sa.Column(name, sa.DateTime(timezone=True), nullable=True)
    return sa.Column(name, sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)


def _location(prefix: str) -> list[sa.Column]:
    return [
        sa.Column(f"{prefix}_lat", sa.Numeric(9, 6), nullable=True),
        sa.Column(f"{prefix}_lng", sa.Numeric(9, 6), nullable=True),
        sa.Column(f"{prefix}_accuracy_m", sa.Numeric(8, 1), nullable=True),
        sa.Column(f"{prefix}_distance_m", sa.Numeric(10, 1), nullable=True),
    ]


def upgrade() -> None:
    t = "attendance_workplaces"
    op.create_table(
        t,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("address", sa.String(255), nullable=True),
        sa.Column("latitude", sa.Numeric(9, 6), nullable=True),
        sa.Column("longitude", sa.Numeric(9, 6), nullable=True),
        sa.Column("radius_m", sa.Integer(), server_default="100", nullable=False),
        sa.Column("is_default", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("open_before_min", sa.Integer(), server_default="30", nullable=False),
        sa.Column("absent_after_min", sa.Integer(), server_default="45", nullable=False),
        sa.Column("checkout_window_min", sa.Integer(), server_default="59", nullable=False),
        sa.Column("max_accuracy_m", sa.Integer(), server_default="100", nullable=False),
        sa.Column("reminders_enabled", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        _ts("archived_at"),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        _ts("created_at", nullable=False),
        _ts("updated_at", nullable=False),
        sa.CheckConstraint(
            "(latitude IS NULL) = (longitude IS NULL)", name=f"ck_{t}_coordinates_together"
        ),
        sa.CheckConstraint(
            "latitude IS NULL OR latitude BETWEEN -90 AND 90", name=f"ck_{t}_latitude"
        ),
        sa.CheckConstraint(
            "longitude IS NULL OR longitude BETWEEN -180 AND 180", name=f"ck_{t}_longitude"
        ),
        sa.CheckConstraint("radius_m BETWEEN 10 AND 5000", name=f"ck_{t}_radius"),
        sa.CheckConstraint(
            "open_before_min > 0 AND open_before_min <= 120", name=f"ck_{t}_open_before"
        ),
        sa.CheckConstraint(
            "absent_after_min > 0 AND absent_after_min <= 240", name=f"ck_{t}_absent_after"
        ),
        sa.CheckConstraint(
            "checkout_window_min >= 0 AND checkout_window_min <= 180",
            name=f"ck_{t}_checkout_window",
        ),
        sa.CheckConstraint("max_accuracy_m BETWEEN 10 AND 500", name=f"ck_{t}_max_accuracy"),
        sa.CheckConstraint("is_active OR NOT is_default", name=f"ck_{t}_default_active"),
        _user_fk(t, "created_by"),
        _user_fk(t, "updated_by"),
        sa.PrimaryKeyConstraint("id", name=f"pk_{t}"),
    )
    op.create_index(
        f"uq_{t}_default", t, ["is_default"], unique=True, postgresql_where=sa.text("is_default")
    )
    op.create_index(
        f"uq_{t}_name_active",
        t,
        [sa.text("lower(name)")],
        unique=True,
        postgresql_where=sa.text("is_active"),
    )
    default_id = uuid.uuid4()
    op.execute(
        sa.text(f"INSERT INTO {t} (id, name, is_default) VALUES (:id, :name, true)").bindparams(
            id=default_id, name=DEFAULT_WORKPLACE_NAME
        )
    )

    t = "attendance_shifts"
    op.create_table(
        t,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workplace_id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(16), nullable=False),
        sa.Column("name_km", sa.String(50), nullable=False),
        sa.Column("name_en", sa.String(50), nullable=False),
        sa.Column("start_time", sa.Time(), nullable=False),
        sa.Column("end_time", sa.Time(), nullable=False),
        sa.Column("position", sa.SmallInteger(), nullable=False),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        _ts("updated_at", nullable=False),
        sa.CheckConstraint(_in("code", SHIFT_CODES), name=f"ck_{t}_code"),
        sa.CheckConstraint("start_time < end_time", name=f"ck_{t}_start_before_end"),
        _user_fk(t, "updated_by"),
        sa.ForeignKeyConstraint(
            ["workplace_id"],
            ["attendance_workplaces.id"],
            name=f"fk_{t}_workplace_id_attendance_workplaces",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=f"pk_{t}"),
        sa.UniqueConstraint("workplace_id", "code", name=f"uq_{t}_workplace_code"),
    )
    op.execute(
        sa.text(
            f"INSERT INTO {t} (id, workplace_id, code, name_km, name_en, start_time, end_time, "
            "position) VALUES "
            "(:m, :w, 'morning', 'វេនព្រឹក', 'Morning shift', '07:00', '12:00', 1), "
            "(:a, :w, 'afternoon', 'វេនរសៀល', 'Afternoon shift', '13:00', '15:00', 2)"
        ).bindparams(m=uuid.uuid4(), a=uuid.uuid4(), w=default_id)
    )

    t = "attendance_records"
    op.create_table(
        t,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("work_date", sa.Date(), nullable=False),
        sa.Column("shift_code", sa.String(16), nullable=False),
        sa.Column("workplace_id", sa.Uuid(), nullable=True),
        sa.Column("scheduled_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("scheduled_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("late_minutes", sa.Integer(), server_default="0", nullable=False),
        _ts("check_in_at"),
        *_location("check_in"),
        sa.Column("checkout_status", sa.String(16), nullable=True),
        _ts("check_out_at"),
        *_location("check_out"),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("corrected", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("correction_reason", sa.String(500), nullable=True),
        sa.Column("corrected_by", sa.Uuid(), nullable=True),
        _ts("corrected_at"),
        _ts("created_at", nullable=False),
        _ts("updated_at", nullable=False),
        sa.CheckConstraint(_in("shift_code", SHIFT_CODES), name=f"ck_{t}_shift_code"),
        sa.CheckConstraint(_in("status", ("present", "late", "absent")), name=f"ck_{t}_status"),
        sa.CheckConstraint(
            "checkout_status IS NULL OR "
            + _in("checkout_status", ("checked_out", "forgot_checkout")),
            name=f"ck_{t}_checkout_status",
        ),
        sa.CheckConstraint(
            _in("source", ("mini_app", "auto", "correction")), name=f"ck_{t}_source"
        ),
        sa.CheckConstraint("late_minutes >= 0", name=f"ck_{t}_late_minutes"),
        sa.CheckConstraint(
            "(status = 'absent') = (check_in_at IS NULL)", name=f"ck_{t}_check_in_matches_status"
        ),
        sa.CheckConstraint(
            "status <> 'absent' OR (checkout_status IS NULL AND check_out_at IS NULL)",
            name=f"ck_{t}_absent_no_checkout",
        ),
        sa.CheckConstraint(
            "check_out_at IS NULL OR checkout_status = 'checked_out'",
            name=f"ck_{t}_check_out_matches",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=f"fk_{t}_user_id_users", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["workplace_id"],
            ["attendance_workplaces.id"],
            name=f"fk_{t}_workplace_id_attendance_workplaces",
            ondelete="SET NULL",
        ),
        _user_fk(t, "corrected_by"),
        sa.PrimaryKeyConstraint("id", name=f"pk_{t}"),
        sa.UniqueConstraint("user_id", "work_date", "shift_code", name=f"uq_{t}_shift"),
    )
    op.create_index(f"ix_{t}_work_date", t, ["work_date", "shift_code"])

    t = "attendance_reminders"
    op.create_table(
        t,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("work_date", sa.Date(), nullable=False),
        sa.Column("shift_code", sa.String(16), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("window_closes_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("telegram_status", sa.String(16), server_default="pending", nullable=False),
        sa.Column("telegram_error", sa.Text(), nullable=True),
        _ts("created_at", nullable=False),
        _ts("sent_at"),
        sa.CheckConstraint(_in("shift_code", SHIFT_CODES), name=f"ck_{t}_shift_code"),
        sa.CheckConstraint(_in("kind", ("check_in", "check_out")), name=f"ck_{t}_kind"),
        sa.CheckConstraint(
            _in("telegram_status", REMINDER_STATUSES), name=f"ck_{t}_telegram_status"
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=f"fk_{t}_user_id_users", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=f"pk_{t}"),
        sa.UniqueConstraint("user_id", "work_date", "shift_code", "kind", name=f"uq_{t}_once"),
    )
    op.create_index(f"ix_{t}_status", t, ["telegram_status"])

    t = "users"
    op.add_column(t, sa.Column("workplace_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        f"fk_{t}_workplace_id_attendance_workplaces",
        t,
        "attendance_workplaces",
        ["workplace_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.execute(
        sa.text(
            "UPDATE users SET workplace_id = :id WHERE role IN ('staff', 'supervisor')"
        ).bindparams(id=default_id)
    )


def downgrade() -> None:
    # Attendance records are the history of who worked when: refuse to drop them.
    count = op.get_bind().scalar(sa.text("SELECT count(*) FROM attendance_records"))
    if count:
        raise RuntimeError(f"{count} attendance record(s) exist; they can't be downgraded")
    op.drop_constraint("fk_users_workplace_id_attendance_workplaces", "users", type_="foreignkey")
    op.drop_column("users", "workplace_id")
    op.drop_table("attendance_reminders")
    op.drop_table("attendance_records")
    op.drop_table("attendance_shifts")
    op.drop_table("attendance_workplaces")
