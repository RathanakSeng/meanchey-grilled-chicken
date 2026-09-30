from typing import Annotated

from fastapi import APIRouter, Depends, Request, status

from app.bot.notify import bot_username
from app.core.errors import AppError, ErrorCode
from app.deps import CurrentUser, SessionDep, require_permission, require_role
from app.models import Role, User
from app.schemas.auth import MeOut
from app.schemas.notification import TelegramLinkOut
from app.schemas.user import ProfileUpdate
from app.services import auth_service, telegram_link_service, user_service

router = APIRouter(prefix="/me", tags=["me"])

Superadmin = Annotated[User, Depends(require_role(Role.SUPERADMIN))]


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


@router.post("/telegram-link", response_model=TelegramLinkOut)
async def create_telegram_link(
    user: Superadmin, session: SessionDep, request: Request
) -> TelegramLinkOut:
    """A one-time deep link (10 minutes) that binds the Telegram account opening it."""
    try:
        username = await bot_username(request.app.state.telegram)
    except Exception as e:
        raise AppError(
            503, ErrorCode.TELEGRAM_NOT_CONFIGURED, "Telegram bot is not reachable"
        ) from e
    if not username:
        raise AppError(503, ErrorCode.TELEGRAM_NOT_CONFIGURED, "Telegram bot is not configured")
    return await telegram_link_service.create_link(session, user, username)


@router.delete("/telegram-link", status_code=status.HTTP_204_NO_CONTENT)
async def delete_telegram_link(user: Superadmin, session: SessionDep) -> None:
    """Unbind the Telegram account (alerts stop reaching it)."""
    await telegram_link_service.unlink(session, user)
