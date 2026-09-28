from fastapi import APIRouter, status

from app.deps import PendingUser, SessionDep
from app.schemas.auth import (
    ChangePasswordIn,
    LoginIn,
    LogoutIn,
    MeOut,
    RefreshIn,
    TelegramLoginIn,
    TokenOut,
)
from app.services import auth_service

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenOut)
async def login(body: LoginIn, session: SessionDep) -> TokenOut:
    """Password login with the account's login name (the Telegram username for staff accounts)."""
    return await auth_service.login_with_password(session, body.username, body.password)


@router.post("/telegram", response_model=TokenOut)
async def telegram_login(body: TelegramLoginIn, session: SessionDep) -> TokenOut:
    """Telegram Mini App login with `Telegram.WebApp.initData`."""
    return await auth_service.login_with_telegram(session, body.init_data)


@router.post("/refresh", response_model=TokenOut)
async def refresh(body: RefreshIn, session: SessionDep) -> TokenOut:
    """Rotate a refresh token: the old one is revoked, a new pair is returned."""
    return await auth_service.refresh_tokens(session, body.refresh_token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(body: LogoutIn, user: PendingUser, session: SessionDep) -> None:
    await auth_service.logout(session, user, body.refresh_token, body.all_sessions)


@router.post("/change-password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(body: ChangePasswordIn, user: PendingUser, session: SessionDep) -> None:
    await auth_service.change_password(session, user, body.current_password, body.new_password)


@router.get("/me", response_model=MeOut)
async def me(user: PendingUser, session: SessionDep) -> MeOut:
    """Current user, effective permission codes and the roles they can manage."""
    return await auth_service.build_me(session, user)
