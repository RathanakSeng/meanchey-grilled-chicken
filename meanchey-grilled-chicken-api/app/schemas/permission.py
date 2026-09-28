import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models import Role


class PermissionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    code: str
    module: str
    name_en: str
    name_km: str
    description_en: str
    description_km: str
    assignable_to: list[Role]


class PermissionModuleOut(BaseModel):
    module: str
    name_en: str
    name_km: str
    permissions: list[PermissionOut]


class UserPermissionOut(PermissionOut):
    granted: bool
    granted_by: uuid.UUID | None
    granted_at: datetime | None
    can_edit: bool
    # Error code of the first rule blocking the actor from editing this item, or null.
    reason: str | None


class UserPermissionModuleOut(BaseModel):
    module: str
    name_en: str
    name_km: str
    permissions: list[UserPermissionOut]


class UserPermissionsOut(BaseModel):
    user_id: uuid.UUID
    modules: list[UserPermissionModuleOut]
