"""How many active users each role may have (general manager, supervisor, staff).

One row per role, set by the superadmin. `max_active` null means unlimited (not allowed for the
general manager). The superadmin itself is always exactly one (`uq_users_single_superadmin`) and
has no row here. Enforced in `services/role_limit_service.ensure_slot`: the row is locked
(`FOR UPDATE`) while active users are counted, so concurrent requests can't both take the last slot.
"""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, utcnow
from app.models.enums import Role

LIMITED_ROLES: tuple[Role, ...] = (Role.GENERAL_MANAGER, Role.SUPERVISOR, Role.STAFF)
DEFAULT_ROLE_LIMITS: dict[Role, int] = {
    Role.GENERAL_MANAGER: 2,
    Role.SUPERVISOR: 3,
    Role.STAFF: 10,
}
MAX_ROLE_LIMIT = 999


class RoleLimit(Base):
    __tablename__ = "role_limits"
    __table_args__ = (
        CheckConstraint("role IN ('general_manager', 'supervisor', 'staff')", name="role"),
        CheckConstraint(
            f"max_active IS NULL OR max_active BETWEEN 1 AND {MAX_ROLE_LIMIT}", name="max_active"
        ),
        CheckConstraint("role <> 'general_manager' OR max_active IS NOT NULL", name="gm_limited"),
    )

    role: Mapped[str] = mapped_column(String(32), primary_key=True)
    # Null = unlimited (supervisor and staff only).
    max_active: Mapped[int | None] = mapped_column(Integer)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )
