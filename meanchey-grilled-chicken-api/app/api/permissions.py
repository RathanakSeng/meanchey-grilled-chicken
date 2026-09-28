import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.deps import CurrentUser, SessionDep, require_permission
from app.models import User
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

CanView = Annotated[User, Depends(require_permission("users.view"))]
CanGrant = Annotated[User, Depends(require_permission("permissions.grant"))]


@router.get("/permissions", response_model=list[PermissionModuleOut])
async def list_permissions(_: CurrentUser, session: SessionDep) -> list[PermissionModuleOut]:
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
    user_id: uuid.UUID, actor: CanView, session: SessionDep
) -> UserPermissionsOut:
    """Permissions assignable to the user's role, with grant state and actor editability."""
    target = await get_user_or_404(session, user_id)
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
                    )
                    for s in g.permissions
                ],
            )
            for g in groups
        ],
    )


@router.put("/users/{user_id}/permissions/{code}", status_code=status.HTTP_204_NO_CONTENT)
async def grant_permission(
    user_id: uuid.UUID, code: str, actor: CanGrant, session: SessionDep
) -> None:
    target = await get_user_or_404(session, user_id)
    await perm_service.grant(session, actor, target, code)


@router.delete("/users/{user_id}/permissions/{code}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_permission(
    user_id: uuid.UUID, code: str, actor: CanGrant, session: SessionDep
) -> None:
    target = await get_user_or_404(session, user_id)
    await perm_service.revoke(session, actor, target, code)
