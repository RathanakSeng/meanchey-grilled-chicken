from pydantic import BaseModel, Field

from app.models import Role
from app.schemas.user import UserOut


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class TelegramLoginIn(BaseModel):
    init_data: str = Field(min_length=1, max_length=4096)


class RefreshIn(BaseModel):
    refresh_token: str = Field(min_length=1, max_length=256)


class LogoutIn(BaseModel):
    refresh_token: str | None = Field(default=None, max_length=256)
    all_sessions: bool = False


class ChangePasswordIn(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=1, max_length=128)


class TokenOut(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    must_change_password: bool


class MeOut(BaseModel):
    user: UserOut
    permissions: list[str]
    manageable_roles: list[Role]
    can_self_reset_password: bool
    # Holds permissions.grant (GM, superadmin) or users.manage_access (supervisor: staff only,
    # capped by their own access): may set feature access levels (Access tab).
    can_manage_features: bool
