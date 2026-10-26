"""Attendance: workplaces, their schedule versions, holidays, one record per employee / day /
shift, reminders sent.

- `attendance_workplaces`: where people check in (GPS position + radius). Exactly one active
  workplace is the default; every tracked employee (active staff and supervisors) is assigned to
  one. Archived (`is_active` false, `archived_at`) when it has attendance history and is deleted.
- `attendance_schedule_versions`: each workplace's schedule from a date on: tracked weekdays,
  the two shifts (`morning`, `afternoon`, local start / end) and the rules (window lengths, GPS
  accuracy limit, extra-time flags, reminders). The schedule on a date is the latest version
  with `effective_from` <= that date.
- `attendance_holidays` (+ `attendance_holiday_workplaces` for `scope = selected`): whole days
  without attendance; `scope = all` also covers workplaces created later.
- `attendance_records`: one per (user, work_date, shift). Shift times are **snapshotted** on the
  record, so later changes never rewrite history; so are the workplace's "count early check-in /
  overtime" flags. Late, early and overtime minutes are stored, so summaries are sums.
- `attendance_reminders`: one per (user, work_date, shift, kind), so each reminder goes out once.
- `attendance_employee_overrides`: an employee's own weekdays / shifts / shift times from a date
  on (null fields inherit the workplace's); `attendance_holiday_exceptions`: who works on a
  holiday day.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, utcnow

SHIFT_CODES = ("morning", "afternoon")
RECORD_STATUSES = ("present", "late", "absent")
CHECKOUT_STATUSES = ("checked_out", "forgot_checkout")
RECORD_SOURCES = ("mini_app", "auto", "correction")
REMINDER_KINDS = ("check_in", "check_out")
# pending: stored, not sent yet; sending: claimed by a scheduler tick (never sent twice);
# skipped: its window closed before it could be sent.
REMINDER_STATUSES = ("pending", "sending", "sent", "failed", "not_linked", "bot_off", "skipped")

WORKPLACE_NAME_MAX_LENGTH = 100
WORKPLACE_ADDRESS_MAX_LENGTH = 255
RADIUS_MIN_M = 10
RADIUS_MAX_M = 5000
DEFAULT_RADIUS_M = 100
OPEN_BEFORE_MAX = 120
ABSENT_AFTER_MAX = 240
CHECKOUT_WINDOW_MAX = 180
REASON_MAX_LENGTH = 500
HOLIDAY_SCOPES = ("all", "selected")
HOLIDAY_NAME_MAX_LENGTH = 100
HOLIDAY_NOTE_MAX_LENGTH = 500
HOLIDAY_MAX_DAYS = 31


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def _user_fk() -> ForeignKey:
    return ForeignKey("users.id", ondelete="SET NULL")


class AttendanceWorkplace(Base):
    __tablename__ = "attendance_workplaces"
    __table_args__ = (
        CheckConstraint("(latitude IS NULL) = (longitude IS NULL)", name="coordinates_together"),
        CheckConstraint("latitude IS NULL OR latitude BETWEEN -90 AND 90", name="latitude"),
        CheckConstraint("longitude IS NULL OR longitude BETWEEN -180 AND 180", name="longitude"),
        CheckConstraint(f"radius_m BETWEEN {RADIUS_MIN_M} AND {RADIUS_MAX_M}", name="radius"),
        CheckConstraint("is_active OR NOT is_default", name="default_active"),
        # Exactly one default (the migration and bootstrap create it).
        Index(
            "uq_attendance_workplaces_default",
            "is_default",
            unique=True,
            postgresql_where=text("is_default"),
        ),
        Index(
            "uq_attendance_workplaces_name_active",
            text("lower(name)"),
            unique=True,
            postgresql_where=text("is_active"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(WORKPLACE_NAME_MAX_LENGTH))
    address: Mapped[str | None] = mapped_column(String(WORKPLACE_ADDRESS_MAX_LENGTH))
    # Null until the superadmin sets them: check-in is refused (ATTENDANCE_WORKPLACE_NOT_SET).
    latitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    longitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    radius_m: Mapped[int] = mapped_column(
        Integer, default=DEFAULT_RADIUS_M, server_default=text(str(DEFAULT_RADIUS_M))
    )
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[uuid.UUID | None] = mapped_column(_user_fk())
    updated_by: Mapped[uuid.UUID | None] = mapped_column(_user_fk())
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )

    @property
    def has_coordinates(self) -> bool:
        return self.latitude is not None and self.longitude is not None


class AttendanceScheduleVersion(Base):
    """A workplace's schedule from `effective_from` on (until its next version). `shifts` holds
    both shifts as `{code, name_km, name_en, start_time "HH:MM", end_time, position}`."""

    __tablename__ = "attendance_schedule_versions"
    __table_args__ = (
        UniqueConstraint(
            "workplace_id", "effective_from", name="uq_attendance_schedule_versions_date"
        ),
        CheckConstraint(
            "cardinality(weekdays) BETWEEN 1 AND 7 "
            "AND weekdays <@ ARRAY[1, 2, 3, 4, 5, 6, 7]::smallint[]",
            name="weekdays",
        ),
        CheckConstraint(
            f"open_before_min > 0 AND open_before_min <= {OPEN_BEFORE_MAX}", name="open_before"
        ),
        CheckConstraint(
            f"absent_after_min > 0 AND absent_after_min <= {ABSENT_AFTER_MAX}",
            name="absent_after",
        ),
        CheckConstraint(
            f"checkout_window_min >= 0 AND checkout_window_min <= {CHECKOUT_WINDOW_MAX}",
            name="checkout_window",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    workplace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(
            "attendance_workplaces.id",
            ondelete="CASCADE",
            name="fk_attendance_schedule_versions_workplace",
        )
    )
    effective_from: Mapped[date] = mapped_column(Date)
    # ISO weekdays (Monday = 1 ... Sunday = 7) when attendance is tracked.
    weekdays: Mapped[list[int]] = mapped_column(ARRAY(SmallInteger))
    shifts: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    open_before_min: Mapped[int] = mapped_column(Integer)
    absent_after_min: Mapped[int] = mapped_column(Integer)
    checkout_window_min: Mapped[int] = mapped_column(Integer)
    # Whether early check-ins / overtime check-outs count as extra time (new records only).
    count_early_checkin: Mapped[bool] = mapped_column(Boolean)
    count_overtime: Mapped[bool] = mapped_column(Boolean)
    reminders_enabled: Mapped[bool] = mapped_column(Boolean)
    created_by: Mapped[uuid.UUID | None] = mapped_column(_user_fk())
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )


class AttendanceHoliday(Base):
    """Whole days without attendance, for every workplace (`all`, later ones too) or the
    workplaces in `attendance_holiday_workplaces` (`selected`)."""

    __tablename__ = "attendance_holidays"
    __table_args__ = (
        CheckConstraint(_in("scope", HOLIDAY_SCOPES), name="scope"),
        CheckConstraint(
            f"end_date >= start_date AND end_date - start_date < {HOLIDAY_MAX_DAYS}", name="dates"
        ),
        Index("ix_attendance_holidays_dates", "start_date", "end_date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name_km: Mapped[str] = mapped_column(String(HOLIDAY_NAME_MAX_LENGTH))
    name_en: Mapped[str] = mapped_column(String(HOLIDAY_NAME_MAX_LENGTH))
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    scope: Mapped[str] = mapped_column(String(16))
    note: Mapped[str | None] = mapped_column(String(HOLIDAY_NOTE_MAX_LENGTH))
    created_by: Mapped[uuid.UUID | None] = mapped_column(_user_fk())
    updated_by: Mapped[uuid.UUID | None] = mapped_column(_user_fk())
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )


class AttendanceHolidayWorkplace(Base):
    __tablename__ = "attendance_holiday_workplaces"

    holiday_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(
            "attendance_holidays.id",
            ondelete="CASCADE",
            name="fk_attendance_holiday_workplaces_holiday",
        ),
        primary_key=True,
    )
    workplace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(
            "attendance_workplaces.id",
            ondelete="CASCADE",
            name="fk_attendance_holiday_workplaces_workplace",
        ),
        primary_key=True,
        index=True,
    )


class AttendanceRecord(Base):
    __tablename__ = "attendance_records"
    __table_args__ = (
        UniqueConstraint("user_id", "work_date", "shift_code", name="uq_attendance_records_shift"),
        CheckConstraint(_in("shift_code", SHIFT_CODES), name="shift_code"),
        CheckConstraint(_in("status", RECORD_STATUSES), name="status"),
        CheckConstraint(
            "checkout_status IS NULL OR " + _in("checkout_status", CHECKOUT_STATUSES),
            name="checkout_status",
        ),
        CheckConstraint(_in("source", RECORD_SOURCES), name="source"),
        CheckConstraint("late_minutes >= 0", name="late_minutes"),
        CheckConstraint("early_minutes >= 0", name="early_minutes"),
        CheckConstraint("overtime_minutes >= 0", name="overtime_minutes"),
        # Absent: no check-in, nothing to check out. Present / late: checked in.
        CheckConstraint(
            "(status = 'absent') = (check_in_at IS NULL)", name="check_in_matches_status"
        ),
        CheckConstraint(
            "status <> 'absent' OR (checkout_status IS NULL AND check_out_at IS NULL)",
            name="absent_no_checkout",
        ),
        CheckConstraint(
            "check_out_at IS NULL OR checkout_status = 'checked_out'", name="check_out_matches"
        ),
        Index("ix_attendance_records_work_date", "work_date", "shift_code"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    work_date: Mapped[date] = mapped_column(Date)
    shift_code: Mapped[str] = mapped_column(String(16))
    workplace_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("attendance_workplaces.id", ondelete="SET NULL")
    )
    # Snapshot of the shift's times on that day (timestamptz).
    scheduled_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    scheduled_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16))
    late_minutes: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    # Before the scheduled start (at most open_before_min) / after the scheduled end (at most
    # checkout_window_min); 0 when the snapshot flag below was off.
    early_minutes: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    overtime_minutes: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    early_counts: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    overtime_counts: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=text("true")
    )
    check_in_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    check_in_lat: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    check_in_lng: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    check_in_accuracy_m: Mapped[Decimal | None] = mapped_column(Numeric(8, 1))
    check_in_distance_m: Mapped[Decimal | None] = mapped_column(Numeric(10, 1))
    checkout_status: Mapped[str | None] = mapped_column(String(16))
    check_out_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    check_out_lat: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    check_out_lng: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    check_out_accuracy_m: Mapped[Decimal | None] = mapped_column(Numeric(8, 1))
    check_out_distance_m: Mapped[Decimal | None] = mapped_column(Numeric(10, 1))
    source: Mapped[str] = mapped_column(String(16))
    corrected: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    correction_reason: Mapped[str | None] = mapped_column(String(REASON_MAX_LENGTH))
    corrected_by: Mapped[uuid.UUID | None] = mapped_column(_user_fk())
    corrected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )


class AttendanceReminder(Base):
    __tablename__ = "attendance_reminders"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "work_date", "shift_code", "kind", name="uq_attendance_reminders_once"
        ),
        CheckConstraint(_in("shift_code", SHIFT_CODES), name="shift_code"),
        CheckConstraint(_in("kind", REMINDER_KINDS), name="kind"),
        CheckConstraint(_in("telegram_status", REMINDER_STATUSES), name="telegram_status"),
        Index("ix_attendance_reminders_status", "telegram_status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    work_date: Mapped[date] = mapped_column(Date)
    shift_code: Mapped[str] = mapped_column(String(16))
    kind: Mapped[str] = mapped_column(String(16))
    # When the window closes: a reminder still unsent then is skipped, never sent late.
    window_closes_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    telegram_status: Mapped[str] = mapped_column(
        String(16), default="pending", server_default=text("'pending'")
    )
    telegram_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AttendanceUntrackedPeriod(Base):
    """A stretch of days a supervisor's attendance was switched off (`to_date` null = ongoing).
    Kept as history: those days show as "Not tracked" and count in no KPI."""

    __tablename__ = "attendance_untracked_periods"
    __table_args__ = (
        CheckConstraint("to_date IS NULL OR to_date >= from_date", name="range"),
        Index("ix_attendance_untracked_periods_user", "user_id", "from_date"),
        Index(
            "uq_attendance_untracked_periods_open",
            "user_id",
            unique=True,
            postgresql_where=text("to_date IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    from_date: Mapped[date] = mapped_column(Date)
    to_date: Mapped[date | None] = mapped_column(Date)
    set_by: Mapped[uuid.UUID | None] = mapped_column(_user_fk())
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )


class AttendanceEmployeeOverride(Base):
    """An employee's own schedule from `effective_from` on (until their next version), on top of
    their workplace's version for the date. Each field is **null = inherit** from the workplace:
    `weekdays` (ISO), `shift_codes` (which of the workplace's shifts they work, 1–2) and
    `shift_times` (`{code: {start_time, end_time}}` for the shifts whose times differ). A version
    with every field null is "back to the workplace schedule". The rules always come from the
    workplace.

    `kept_shifts` is set only on a version effective on the day it was saved: the shifts of that
    day whose check-in had already opened (`{code: {start_time, end_time}}`), which keep the
    previous setting on that day."""

    __tablename__ = "attendance_employee_overrides"
    __table_args__ = (
        UniqueConstraint("user_id", "effective_from", name="uq_attendance_employee_overrides_date"),
        CheckConstraint(
            "weekdays IS NULL OR (cardinality(weekdays) BETWEEN 1 AND 7 "
            "AND weekdays <@ ARRAY[1, 2, 3, 4, 5, 6, 7]::smallint[])",
            name="weekdays",
        ),
        CheckConstraint(
            "shift_codes IS NULL OR cardinality(shift_codes) BETWEEN 1 AND 2", name="shift_codes"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE", name="fk_attendance_employee_overrides_user")
    )
    effective_from: Mapped[date] = mapped_column(Date)
    weekdays: Mapped[list[int] | None] = mapped_column(ARRAY(SmallInteger))
    shift_codes: Mapped[list[str] | None] = mapped_column(ARRAY(String(32)))
    shift_times: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    kept_shifts: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_by: Mapped[uuid.UUID | None] = mapped_column(_user_fk())
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )


class AttendanceHolidayException(Base):
    """An employee who works on one day of a holiday: `shift_codes` / `shift_times` null = their
    normal shifts and times."""

    __tablename__ = "attendance_holiday_exceptions"
    __table_args__ = (
        UniqueConstraint(
            "holiday_id", "user_id", "date", name="uq_attendance_holiday_exceptions_day"
        ),
        CheckConstraint(
            "shift_codes IS NULL OR cardinality(shift_codes) BETWEEN 1 AND 2", name="shift_codes"
        ),
        Index("ix_attendance_holiday_exceptions_user", "user_id", "date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    holiday_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(
            "attendance_holidays.id",
            ondelete="CASCADE",
            name="fk_attendance_holiday_exceptions_holiday",
        )
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE", name="fk_attendance_holiday_exceptions_user")
    )
    day: Mapped[date] = mapped_column("date", Date)
    shift_codes: Mapped[list[str] | None] = mapped_column(ARRAY(String(32)))
    shift_times: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_by: Mapped[uuid.UUID | None] = mapped_column(_user_fk())
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )


REQUEST_STATUSES = ("pending", "approved", "rejected")
REQUEST_TYPES = ("salary_cut", "unpaid_work", "both")


class AttendanceRequest(Base):
    """One request per employee and month, sent after the month ends when the missing time is at
    least an hour: how it is covered (salary cut / unpaid extra work / both). The month's figures
    are **snapshotted** at submission. `pending` and `approved` lock the month's records."""

    __tablename__ = "attendance_requests"
    __table_args__ = (
        UniqueConstraint("user_id", "year", "month", name="uq_attendance_requests_month"),
        CheckConstraint(_in("status", REQUEST_STATUSES), name="status"),
        CheckConstraint(_in("type", REQUEST_TYPES), name="type"),
        CheckConstraint("month BETWEEN 1 AND 12", name="month"),
        CheckConstraint(
            "requested_salary_cut_minutes >= 0 AND requested_unpaid_work_minutes >= 0 "
            "AND requested_salary_cut_minutes + requested_unpaid_work_minutes = missing_minutes",
            name="requested_split",
        ),
        CheckConstraint(
            "(approved_salary_cut_minutes IS NULL) = (approved_unpaid_work_minutes IS NULL) "
            "AND (approved_salary_cut_minutes IS NULL OR (approved_salary_cut_minutes >= 0 "
            "AND approved_unpaid_work_minutes >= 0 AND approved_salary_cut_minutes "
            "+ approved_unpaid_work_minutes = missing_minutes))",
            name="approved_split",
        ),
        Index("ix_attendance_requests_status", "status", "submitted_at"),
        Index("ix_attendance_requests_month", "year", "month"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    year: Mapped[int] = mapped_column(SmallInteger)
    month: Mapped[int] = mapped_column(SmallInteger)
    status: Mapped[str] = mapped_column(String(16), default="pending")
    # The month as it was when the request was sent.
    missing_minutes: Mapped[int] = mapped_column(Integer)
    extra_minutes: Mapped[int] = mapped_column(Integer)
    absent_minutes: Mapped[int] = mapped_column(Integer)
    late_minutes: Mapped[int] = mapped_column(Integer)
    balance_minutes: Mapped[int] = mapped_column(Integer)
    requested_salary_cut_minutes: Mapped[int] = mapped_column(Integer)
    requested_unpaid_work_minutes: Mapped[int] = mapped_column(Integer)
    # Null until approved.
    approved_salary_cut_minutes: Mapped[int | None] = mapped_column(Integer)
    approved_unpaid_work_minutes: Mapped[int | None] = mapped_column(Integer)
    type: Mapped[str] = mapped_column(String(16))  # of the requested split
    approved_with_changes: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false")
    )
    note: Mapped[str | None] = mapped_column(String(500))
    review_comment: Mapped[str | None] = mapped_column(String(500))
    reject_reason: Mapped[str | None] = mapped_column(String(500))
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(_user_fk())
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
