"""System settings, superadmin only (role limits)."""

from typing import Annotated

from fastapi import APIRouter, Depends

from app.deps import SessionDep, require_role
from app.models import Role, User
from app.schemas.role_limit import RoleLimitIn, RoleLimitOut
from app.services import role_limit_service

router = APIRouter(prefix="/settings", tags=["settings"])

Superadmin = Annotated[User, Depends(require_role(Role.SUPERADMIN))]


@router.get("/role-limits", response_model=list[RoleLimitOut])
async def list_role_limits(_: Superadmin, session: SessionDep) -> list[RoleLimitOut]:
    """Limit, active count and over-limit flag for general managers, supervisors and staff."""
    return await role_limit_service.list_limits(session)


@router.put("/role-limits/{role}", response_model=list[RoleLimitOut])
async def set_role_limit(
    role: Role, body: RoleLimitIn, actor: Superadmin, session: SessionDep
) -> list[RoleLimitOut]:
    """1–999, or null = unlimited (supervisor, staff). Lowering below the active count keeps
    everyone active; the role is full until enough users leave it."""
    return await role_limit_service.set_limit(session, actor, role, body.max_active)
