"""attendance scheduling: schedule versions per workplace, holidays, attendance.scheduling

- `attendance_schedule_versions`: one row per workplace and `effective_from` date with the tracked
  weekdays, both shifts (JSONB) and the rules. Each workplace's current schedule (its
  `attendance_shifts` and rule columns) becomes one version from the workplace's creation date
  (business time zone) with all seven weekdays; then `attendance_shifts` and the rule columns
  are dropped.
- `attendance_holidays` and `attendance_holiday_workplaces` (for `scope = selected`).
- `attendance.shifts_manage` is retired: every user holding it gets `attendance.scheduling`
  instead (the permission row is inserted here; the startup sync fills the rest and marks
  `shifts_manage` inactive). One `feature.set` audit entry per changed user, no actor,
  `details.source = "default_change"`.

Downgrade puts each workplace's latest version back into the rule columns and
`attendance_shifts` and drops the new tables (holidays and older versions are lost); the
permission change stays.

Revision ID: 0020
Revises: 0019
Create Date: 2026-10-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.config import get_settings

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

W = "attendance_workplaces"
RULES = (
    ("open_before_min", sa.Integer(), "30"),
    ("absent_after_min", sa.Integer(), "45"),
    ("checkout_window_min", sa.Integer(), "59"),
    ("max_accuracy_m", sa.Integer(), "100"),
    ("reminders_enabled", sa.Boolean(), "true"),
    ("count_early_checkin", sa.Boolean(), "true"),
    ("count_overtime", sa.Boolean(), "true"),
)
RULE_CHECKS = (
    ("open_before", "open_before_min > 0 AND open_before_min <= 120"),
    ("absent_after", "absent_after_min > 0 AND absent_after_min <= 240"),
    ("checkout_window", "checkout_window_min >= 0 AND checkout_window_min <= 180"),
    ("max_accuracy", "max_accuracy_m BETWEEN 10 AND 500"),
)


def _user_fk(t: str, column: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        [column], ["users.id"], name=f"fk_{t}_{column}_users", ondelete="SET NULL"
    )


def _ts(name: str) -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)


def upgrade() -> None:
    zone = get_settings().business_timezone

    t = "attendance_schedule_versions"
    op.create_table(
        t,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workplace_id", sa.Uuid(), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("weekdays", postgresql.ARRAY(sa.SmallInteger()), nullable=False),
        sa.Column("shifts", postgresql.JSONB(), nullable=False),
        *(sa.Column(name, type_, nullable=False) for name, type_, _ in RULES),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        _ts("created_at"),
        sa.CheckConstraint(
            "cardinality(weekdays) BETWEEN 1 AND 7 "
            "AND weekdays <@ ARRAY[1, 2, 3, 4, 5, 6, 7]::smallint[]",
            name=f"ck_{t}_weekdays",
        ),
        *(sa.CheckConstraint(sql, name=f"ck_{t}_{name}") for name, sql in RULE_CHECKS),
        sa.ForeignKeyConstraint(
            ["workplace_id"], [f"{W}.id"], name=f"fk_{t}_workplace", ondelete="CASCADE"
        ),
        _user_fk(t, "created_by"),
        sa.PrimaryKeyConstraint("id", name=f"pk_{t}"),
        sa.UniqueConstraint("workplace_id", "effective_from", name=f"uq_{t}_date"),
    )
    op.execute(
        sa.text(
            f"""
            INSERT INTO {t} (id, workplace_id, effective_from, weekdays, shifts, open_before_min,
                absent_after_min, checkout_window_min, max_accuracy_m, reminders_enabled,
                count_early_checkin, count_overtime, created_by, created_at)
            SELECT gen_random_uuid(), w.id, (w.created_at AT TIME ZONE :zone)::date,
                ARRAY[1, 2, 3, 4, 5, 6, 7]::smallint[],
                COALESCE((
                    SELECT jsonb_agg(jsonb_build_object(
                        'code', s.code, 'name_km', s.name_km, 'name_en', s.name_en,
                        'start_time', to_char(s.start_time, 'HH24:MI'),
                        'end_time', to_char(s.end_time, 'HH24:MI'),
                        'position', s.position) ORDER BY s.position)
                    FROM attendance_shifts s WHERE s.workplace_id = w.id
                ), '[]'::jsonb),
                w.open_before_min, w.absent_after_min, w.checkout_window_min, w.max_accuracy_m,
                w.reminders_enabled, w.count_early_checkin, w.count_overtime,
                w.created_by, w.created_at
            FROM {W} w
            """
        ).bindparams(zone=zone)
    )
    # A workplace without shifts (never expected) gets the default ones.
    op.execute(
        f"""
        UPDATE {t} SET shifts = '[
            {{"code": "morning", "name_km": "វេនព្រឹក", "name_en": "Morning shift",
              "start_time": "07:00", "end_time": "12:00", "position": 1}},
            {{"code": "afternoon", "name_km": "វេនរសៀល", "name_en": "Afternoon shift",
              "start_time": "13:00", "end_time": "15:00", "position": 2}}
        ]'::jsonb
        WHERE jsonb_array_length(shifts) < 2
        """
    )
    op.drop_table("attendance_shifts")
    for name, _ in RULE_CHECKS:
        op.drop_constraint(f"ck_{W}_{name}", W, type_="check")
    for name, _, _ in RULES:
        op.drop_column(W, name)

    t = "attendance_holidays"
    op.create_table(
        t,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name_km", sa.String(100), nullable=False),
        sa.Column("name_en", sa.String(100), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("scope", sa.String(16), nullable=False),
        sa.Column("note", sa.String(500), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        _ts("created_at"),
        _ts("updated_at"),
        sa.CheckConstraint("scope IN ('all', 'selected')", name=f"ck_{t}_scope"),
        sa.CheckConstraint(
            "end_date >= start_date AND end_date - start_date < 31", name=f"ck_{t}_dates"
        ),
        _user_fk(t, "created_by"),
        _user_fk(t, "updated_by"),
        sa.PrimaryKeyConstraint("id", name=f"pk_{t}"),
    )
    op.create_index(f"ix_{t}_dates", t, ["start_date", "end_date"])

    t = "attendance_holiday_workplaces"
    op.create_table(
        t,
        sa.Column("holiday_id", sa.Uuid(), nullable=False),
        sa.Column("workplace_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["holiday_id"],
            ["attendance_holidays.id"],
            name=f"fk_{t}_holiday",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workplace_id"], [f"{W}.id"], name=f"fk_{t}_workplace", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("holiday_id", "workplace_id", name=f"pk_{t}"),
    )
    op.create_index(f"ix_{t}_workplace_id", t, ["workplace_id"])

    # attendance.shifts_manage -> attendance.scheduling.
    op.execute(
        """
        INSERT INTO permissions (code, module, name_en, name_km, description_en, description_km,
            assignable_to, is_active)
        VALUES ('attendance.scheduling', 'attendance', 'Manage scheduling', 'គ្រប់គ្រងកាលវិភាគ',
            'Tracked weekdays, holidays, shift times and rules, per workplace.',
            'ថ្ងៃតាមដាន ថ្ងៃឈប់សម្រាក ម៉ោងវេន និងច្បាប់ តាមកន្លែងធ្វើការ។',
            ARRAY['general_manager', 'supervisor'], true)
        ON CONFLICT (code) DO NOTHING
        """
    )
    op.execute(
        """
        CREATE TEMP TABLE _shifts_holders ON COMMIT DROP AS
        SELECT user_id, granted_by FROM user_permissions
        WHERE permission_code = 'attendance.shifts_manage'
        """
    )
    op.execute(
        """
        INSERT INTO user_permissions (user_id, permission_code, granted_by)
        SELECT user_id, 'attendance.scheduling', granted_by FROM _shifts_holders
        ON CONFLICT DO NOTHING
        """
    )
    op.execute("DELETE FROM user_permissions WHERE permission_code = 'attendance.shifts_manage'")
    op.execute(
        """
        INSERT INTO audit_logs (actor_id, action, target_user_id, details)
        SELECT NULL, 'feature.set', user_id, jsonb_build_object(
            'feature', 'attendance_scheduling',
            'from', 'off',
            'to', 'full',
            'added', '["attendance.scheduling"]'::jsonb,
            'removed', '["attendance.shifts_manage"]'::jsonb,
            'source', 'default_change'
        )
        FROM _shifts_holders
        """
    )
    op.execute("DROP TABLE _shifts_holders")


def downgrade() -> None:
    op.drop_table("attendance_holiday_workplaces")
    op.drop_table("attendance_holidays")
    for name, type_, default in RULES:
        op.add_column(W, sa.Column(name, type_, server_default=sa.text(default), nullable=False))
    for name, sql in RULE_CHECKS:
        op.create_check_constraint(f"ck_{W}_{name}", W, sql)
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
        _ts("updated_at"),
        sa.CheckConstraint("code IN ('morning', 'afternoon')", name=f"ck_{t}_code"),
        sa.CheckConstraint("start_time < end_time", name=f"ck_{t}_start_before_end"),
        _user_fk(t, "updated_by"),
        sa.ForeignKeyConstraint(
            ["workplace_id"], [f"{W}.id"], name=f"fk_{t}_workplace_id_{W}", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=f"pk_{t}"),
        sa.UniqueConstraint("workplace_id", "code", name=f"uq_{t}_workplace_code"),
    )
    latest = """
        SELECT DISTINCT ON (workplace_id) * FROM attendance_schedule_versions
        ORDER BY workplace_id, effective_from DESC
    """
    op.execute(
        f"""
        UPDATE {W} w SET open_before_min = v.open_before_min,
            absent_after_min = v.absent_after_min, checkout_window_min = v.checkout_window_min,
            max_accuracy_m = v.max_accuracy_m, reminders_enabled = v.reminders_enabled,
            count_early_checkin = v.count_early_checkin, count_overtime = v.count_overtime
        FROM ({latest}) v WHERE v.workplace_id = w.id
        """
    )
    op.execute(
        f"""
        INSERT INTO {t} (id, workplace_id, code, name_km, name_en, start_time, end_time, position)
        SELECT gen_random_uuid(), v.workplace_id, s->>'code', s->>'name_km', s->>'name_en',
            (s->>'start_time')::time, (s->>'end_time')::time, (s->>'position')::smallint
        FROM ({latest}) v, jsonb_array_elements(v.shifts) s
        """
    )
    op.drop_table("attendance_schedule_versions")
