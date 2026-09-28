"""FastAPI dependencies for authentication and authorization.

- `CurrentUser`: an authenticated, active user who does not have to change their password.
- `PendingUser`: same, but also allowed while a password change is pending
  (used only by /auth/me, /auth/change-password and /auth/logout).
- `require_permission(*codes)`, `require_role(*roles)`: route guards returning the current user.
- Scope checks live in `app.permissions.hierarchy.ensure_can_manage`.
"""

from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, ErrorCode
from app.core.security import decode_access_token
from app.db import get_session
from app.models import Role, User
from app.permissions.service import effective_permissions

SessionDep = Annotated[AsyncSession, Depends(get_session)]

_bearer = HTTPBearer(auto_error=False)


async def get_current_user_allow_pending(
    session: SessionDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> User:
    if credentials is None:
        raise AppError(401, ErrorCode.NOT_AUTHENTICATED, "Not authenticated")
    user_id = decode_access_token(credentials.credentials)
    # Reload on every request so deactivation takes effect immediately.
    user = await session.get(User, user_id)
    if user is None:
        raise AppError(401, ErrorCode.INVALID_TOKEN, "Invalid access token")
    if not user.is_active:
        raise AppError(401, ErrorCode.ACCOUNT_DISABLED, "Account is deactivated")
    return user


PendingUser = Annotated[User, Depends(get_current_user_allow_pending)]


async def get_current_user(user: PendingUser) -> User:
    if user.must_change_password:
        raise AppError(
            403, ErrorCode.PASSWORD_CHANGE_REQUIRED, "You must change your password first"
        )
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_permission(*codes: str):
    async def dependency(user: CurrentUser, session: SessionDep) -> User:
        held = await effective_permissions(session, user)
        missing = [c for c in codes if c not in held]
        if missing:
            raise AppError(
                403, ErrorCode.MISSING_PERMISSION, "Missing permission", {"required": missing}
            )
        return user

    return dependency


def require_role(*roles: Role):
    allowed = frozenset(roles)

    async def dependency(user: CurrentUser) -> User:
        if user.role not in allowed:
            raise AppError(
                403,
                ErrorCode.FORBIDDEN_ROLE,
                "Your role cannot access this resource",
                {"allowed_roles": sorted(allowed)},
            )
        return user

    return dependency
