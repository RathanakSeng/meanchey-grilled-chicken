import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, func, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, utcnow


class Permission(Base):
    """Mirror of app/permissions/registry.py, synced on startup. Rows are never deleted."""

    __tablename__ = "permissions"

    code: Mapped[str] = mapped_column(String(64), primary_key=True)
    module: Mapped[str] = mapped_column(String(32), index=True)
    name_en: Mapped[str] = mapped_column(String(120))
    name_km: Mapped[str] = mapped_column(String(120))
    description_en: Mapped[str] = mapped_column(Text)
    description_km: Mapped[str] = mapped_column(Text)
    assignable_to: Mapped[list[str]] = mapped_column(ARRAY(String(32)))
    # {target_role: [grantor_role, ...]}: restricts who may grant/revoke it for that target role.
    grantable_by: Mapped[dict[str, list[str]] | None] = mapped_column(JSONB)
    is_active: Mapped[bool] = mapped_column(default=True, server_default=text("true"))


class UserPermission(Base):
    __tablename__ = "user_permissions"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    permission_code: Mapped[str] = mapped_column(ForeignKey("permissions.code"), primary_key=True)
    granted_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    granted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )
