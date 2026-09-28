import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.deps import SessionDep, require_role
from app.models import Role, User
from app.permissions import service as perm_service
from app.permissions.hierarchy import ensure_can_manage
from app.schemas.permission import (
    PermissionModuleOut,
    PermissionOut,
    UserPermissionModuleOut,
    UserPermissionOut,
    UserPermissionsOut,
)
from app.services.user_service import get_user_or_404

router = APIRouter(tags=["permissions"])

# Detailed permissions are the superadmin's tool. Everyone else manages access through feature
# levels (api/features.py) and gets 403 FORBIDDEN_ROLE here.
Superadmin = Annotated[User, Depends(require_role(Role.SUPERADMIN))]


@router.get("/permissions", response_model=list[PermissionModuleOut])
async def list_permissions(_: Superadmin, session: SessionDep) -> list[PermissionModuleOut]:
    """Active permission catalog, grouped by module."""
    groups = await perm_service.catalog(session)
    return [
        PermissionModuleOut(
            module=g.module,
            name_en=g.name_en,
            name_km=g.name_km,
            permissions=[PermissionOut.model_validate(p) for p in g.permissions],
        )
        for g in groups
    ]


@router.get("/users/{user_id}/permissions", response_model=UserPermissionsOut)
async def get_user_permissions(
    user_id: uuid.UUID, actor: Superadmin, session: SessionDep
) -> UserPermissionsOut:
    """Permissions assignable to the user's role, with grant state and actor editability."""
    target = await get_user_or_404(session, user_id, actor)
    ensure_can_manage(actor, target)
    groups = await perm_service.user_permission_matrix(session, actor, target)
    return UserPermissionsOut(
        user_id=target.id,
        modules=[
            UserPermissionModuleOut(
                module=g.module,
                name_en=g.name_en,
                name_km=g.name_km,
                permissions=[
                    UserPermissionOut(
                        **PermissionOut.model_validate(s.permission).model_dump(),
                        granted=s.granted,
                        granted_by=s.granted_by,
                        granted_at=s.granted_at,
                        can_edit=s.can_edit,
                        reason=s.reason,
                    )
                    for s in g.permissions
                ],
            )
            for g in groups
        ],
    )


@router.put("/users/{user_id}/permissions/{code}", status_code=status.HTTP_204_NO_CONTENT)
async def grant_permission(
    user_id: uuid.UUID, code: str, actor: Superadmin, session: SessionDep
) -> None:
    target = await get_user_or_404(session, user_id, actor)
    await perm_service.grant(session, actor, target, code)


@router.delete("/users/{user_id}/permissions/{code}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_permission(
    user_id: uuid.UUID, code: str, actor: Superadmin, session: SessionDep
) -> None:
    target = await get_user_or_404(session, user_id, actor)
    await perm_service.revoke(session, actor, target, code)
