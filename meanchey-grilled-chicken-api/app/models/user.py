import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    String,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, utcnow
from app.models.enums import Language, Role, language_type, role_type

if TYPE_CHECKING:
    from app.models.attendance import AttendanceUntrackedPeriod, AttendanceWorkplace

POSITION_MAX_LENGTH = 50


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("(role = 'staff') = (position IS NOT NULL)", name="position_staff_only"),
        CheckConstraint(
            "role = 'superadmin' OR telegram_username IS NOT NULL",
            name="telegram_username_required",
        ),
        # Business invariants enforced by the database, not only in code. How many active
        # general managers, supervisors and staff there may be is configurable: role_limits.
        Index(
            "uq_users_single_superadmin",
            "role",
            unique=True,
            postgresql_where=text("role = 'superadmin'"),
        ),
        # Unique among active users so a deactivated account's username can be reused.
        Index(
            "uq_users_active_telegram_username",
            "telegram_username",
            unique=True,
            postgresql_where=text("is_active"),
        ),
        Index(
            "uq_users_active_telegram_user_id",
            "telegram_user_id",
            unique=True,
            postgresql_where=text("is_active"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    role: Mapped[Role] = mapped_column(role_type)
    # Free-text job title for staff. Descriptive only: never used for access control.
    position: Mapped[str | None] = mapped_column(String(POSITION_MAX_LENGTH))
    full_name: Mapped[str] = mapped_column(String(120))
    phone: Mapped[str | None] = mapped_column(String(32))
    telegram_username: Mapped[str | None] = mapped_column(String(32))
    telegram_user_id: Mapped[int | None] = mapped_column(BigInteger)
    password_hash: Mapped[str] = mapped_column(String(255))
    must_change_password: Mapped[bool] = mapped_column(default=True, server_default=text("true"))
    language: Mapped[Language] = mapped_column(
        language_type, default=Language.KM, server_default=Language.KM.value
    )
    is_active: Mapped[bool] = mapped_column(default=True, server_default=text("true"))
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, server_default=func.now()
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failed_login_count: Mapped[int] = mapped_column(default=0, server_default=text("0"))
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Attendance: where a tracked employee (staff, supervisor) checks in. Set to the default
    # workplace on create / role change; null for the general manager and the superadmin.
    workplace_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("attendance_workplaces.id", ondelete="SET NULL")
    )
    # Attendance tracking: the first tracked day (staff and supervisors, null for the others) and
    # whether a supervisor is tracked at all (staff always are). Past switch-offs are kept in
    # `attendance_untracked_periods`.
    attendance_start_date: Mapped[date | None] = mapped_column(Date)
    attendance_tracked: Mapped[bool] = mapped_column(default=True, server_default=text("true"))

    # Loaded eagerly (one extra SELECT per query) so `UserOut.created_by` can be a UserRef.
    creator: Mapped["User | None"] = relationship(
        remote_side=[id], foreign_keys=[created_by], lazy="selectin", join_depth=1
    )

    workplace: Mapped["AttendanceWorkplace | None"] = relationship(
        foreign_keys=[workplace_id], lazy="selectin"
    )

    # Past and ongoing switch-offs of a supervisor's attendance (history, see tracking.py).
    untracked_periods: Mapped[list["AttendanceUntrackedPeriod"]] = relationship(
        "AttendanceUntrackedPeriod",
        foreign_keys="AttendanceUntrackedPeriod.user_id",
        lazy="selectin",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="AttendanceUntrackedPeriod.from_date",
    )

    @property
    def attendance_periods(self) -> list[tuple[date, date | None]]:
        return [(p.from_date, p.to_date) for p in self.untracked_periods]

    @property
    def attendance_untracked_since(self) -> date | None:
        """When the ongoing untracked period began (null while tracked)."""
        return next((p.from_date for p in self.untracked_periods if p.to_date is None), None)

    @property
    def telegram_linked(self) -> bool:
        return self.telegram_user_id is not None
