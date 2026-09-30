import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.core.errors import AppError, ErrorCode
from app.deps import CurrentUser, SessionDep, require_permission
from app.models import Role, User
from app.models.user import POSITION_MAX_LENGTH
from app.permissions.hierarchy import ensure_can_manage
from app.permissions.service import effective_permissions
from app.schemas.role_limit import RoleCapacityOut
from app.schemas.user import RoleChange, UserCreate, UserOut, UserPage, UserStatus, UserUpdate
from app.services import role_limit_service, user_service

router = APIRouter(prefix="/users", tags=["users"])

CanView = Annotated[User, Depends(require_permission("users.view"))]
CanCreate = Annotated[User, Depends(require_permission("users.create"))]
CanUpdate = Annotated[User, Depends(require_permission("users.update"))]
CanDelete = Annotated[User, Depends(require_permission("users.delete"))]
CanResetPassword = Annotated[User, Depends(require_permission("users.reset_password"))]


@router.get("", response_model=UserPage)
async def list_users(
    actor: CanView,
    session: SessionDep,
    role: Role | None = None,
    position: Annotated[str | None, Query(max_length=POSITION_MAX_LENGTH)] = None,
    status: UserStatus = "active",
    q: Annotated[str | None, Query(max_length=100)] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> UserPage:
    """Users within the actor's scope.

    `position` matches case-insensitively; `q` searches name, Telegram, phone and position.
    """
    items, total = await user_service.list_users(
        session,
        actor,
        role=role,
        position=position,
        status=status,
        q=q,
        page=page,
        page_size=page_size,
    )
    return UserPage(
        items=[UserOut.model_validate(u) for u in items],
        total=total,
        page=page,
        page_size=page_size,
    )


# Declared before /{user_id} so "positions" / "role-capacity" aren't parsed as UUIDs.
@router.get("/positions", response_model=list[str])
async def list_positions(actor: CanView, session: SessionDep) -> list[str]:
    """Distinct (case-insensitive) positions of active users in the actor's scope, sorted."""
    return await user_service.list_positions(session, actor)


async def _can_view_or_create(user: CurrentUser, session: SessionDep) -> User:
    held = await effective_permissions(session, user)
    if not {"users.view", "users.create"} & held:
        raise AppError(
            403, ErrorCode.MISSING_PERMISSION, "Missing permission", {"required": ["users.view"]}
        )
    return user


@router.get("/role-capacity", response_model=list[RoleCapacityOut])
async def role_capacity(
    actor: Annotated[User, Depends(_can_view_or_create)], session: SessionDep
) -> list[RoleCapacityOut]:
    """Active users and limit per role the actor manages (GM: supervisor, staff; supervisor:
    staff). `full` = no new active user of that role until someone leaves it."""
    return await role_limit_service.capacity(session, actor)


@router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def create_user(body: UserCreate, actor: CanCreate, session: SessionDep) -> User:
    """Initial password is the Telegram username; the user must change it on first login."""
    return await user_service.create_user(session, actor, body)


@router.get("/{user_id}", response_model=UserOut)
async def get_user(user_id: uuid.UUID, actor: CanView, session: SessionDep) -> User:
    target = await user_service.get_user_or_404(session, user_id, actor)
    ensure_can_manage(actor, target)
    return target


@router.patch("/{user_id}", response_model=UserOut)
async def update_user(
    user_id: uuid.UUID, body: UserUpdate, actor: CanUpdate, session: SessionDep
) -> User:
    target = await user_service.get_user_or_404(session, user_id, actor)
    return await user_service.update_user(session, actor, target, body)


@router.post("/{user_id}/role", response_model=UserOut)
async def change_role(
    user_id: uuid.UUID, body: RoleChange, actor: CanUpdate, session: SessionDep
) -> User:
    """Promote / demote to another role the actor manages. Access resets to the role's defaults."""
    target = await user_service.get_user_or_404(session, user_id, actor)
    return await user_service.change_role(session, actor, target, body)


@router.post("/{user_id}/deactivate", response_model=UserOut)
async def deactivate_user(user_id: uuid.UUID, actor: CanDelete, session: SessionDep) -> User:
    target = await user_service.get_user_or_404(session, user_id, actor)
    return await user_service.deactivate_user(session, actor, target)


@router.post("/{user_id}/reactivate", response_model=UserOut)
async def reactivate_user(user_id: uuid.UUID, actor: CanDelete, session: SessionDep) -> User:
    target = await user_service.get_user_or_404(session, user_id, actor)
    return await user_service.reactivate_user(session, actor, target)


@router.post("/{user_id}/reset-password", status_code=status.HTTP_204_NO_CONTENT)
async def reset_password(user_id: uuid.UUID, actor: CanResetPassword, session: SessionDep) -> None:
    """Password becomes the Telegram username; the user must change it at next login."""
    target = await user_service.get_user_or_404(session, user_id, actor)
    await user_service.reset_password(session, actor, target)
