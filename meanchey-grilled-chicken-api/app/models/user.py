import uuid
from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Index, String, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, utcnow
from app.models.enums import Language, Role, language_type, role_type

POSITION_MAX_LENGTH = 50


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("(role = 'staff') = (position IS NOT NULL)", name="position_staff_only"),
        CheckConstraint(
            "role = 'superadmin' OR telegram_username IS NOT NULL",
            name="telegram_username_required",
        ),
        # Business invariants enforced by the database, not only in code.
        Index(
            "uq_users_single_superadmin",
            "role",
            unique=True,
            postgresql_where=text("role = 'superadmin'"),
        ),
        Index(
            "uq_users_single_active_gm",
            "role",
            unique=True,
            postgresql_where=text("role = 'general_manager' AND is_active"),
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

    # Loaded eagerly (one extra SELECT per query) so `UserOut.created_by` can be a UserRef.
    creator: Mapped["User | None"] = relationship(
        remote_side=[id], foreign_keys=[created_by], lazy="selectin", join_depth=1
    )

    @property
    def telegram_linked(self) -> bool:
        return self.telegram_user_id is not None
