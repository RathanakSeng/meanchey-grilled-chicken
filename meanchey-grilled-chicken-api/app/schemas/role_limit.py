"""Role limits (superadmin settings) and role capacity (for managers)."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models import Role
from app.schemas.common import UserRef


class RoleLimitIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # 1–999; null = unlimited (not for the general manager). Checked by the service.
    max_active: int | None


class RoleLimitOut(BaseModel):
    role: Role
    max_active: int | None
    active: int
    # More active users than the limit (after lowering it): nobody new until some leave.
    over_limit: bool
    updated_by: UserRef | None
    updated_at: datetime | None


class RoleCapacityOut(BaseModel):
    role: Role
    active: int
    # null = unlimited
    limit: int | None
    full: bool
