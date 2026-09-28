from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.deps import CurrentUser, SessionDep, require_permission
from app.models import User
from app.schemas.auth import MeOut
from app.schemas.user import ProfileUpdate
from app.services import auth_service, user_service

router = APIRouter(prefix="/me", tags=["me"])


@router.patch("", response_model=MeOut)
async def update_profile(body: ProfileUpdate, user: CurrentUser, session: SessionDep) -> MeOut:
    """Edit own name, phone and language."""
    await user_service.update_profile(session, user, body)
    return await auth_service.build_me(session, user)


@router.post("/reset-password", status_code=status.HTTP_204_NO_CONTENT)
async def self_reset_password(
    user: Annotated[User, Depends(require_permission("users.reset_password"))],
    session: SessionDep,
) -> None:
    """Reset own password to the default and end all sessions (roles allowed to self-reset)."""
    await user_service.self_reset_password(session, user)
