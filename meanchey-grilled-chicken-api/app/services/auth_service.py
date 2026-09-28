import uuid
from datetime import timedelta

from sqlalchemy import ColumnElement, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.errors import AppError, ErrorCode
from app.core.security import (
    create_access_token,
    hash_password,
    hash_refresh_token,
    new_refresh_token,
    password_needs_rehash,
    verify_password,
)
from app.core.telegram_auth import validate_init_data
from app.core.usernames import SUPERADMIN_USERNAME, normalize_login, normalize_telegram_username
from app.models import RefreshToken, Role, User, utcnow
from app.permissions.hierarchy import manageable_roles
from app.permissions.service import effective_permissions
from app.schemas.auth import MeOut, TokenOut
from app.schemas.user import UserOut
from app.services.audit_service import record

MIN_PASSWORD_LENGTH = 8
SELF_RESET_ROLES = frozenset({Role.SUPERADMIN, Role.GENERAL_MANAGER})


def _login_clause(identifier: str) -> ColumnElement[bool]:
    if identifier == SUPERADMIN_USERNAME:
        return User.role == Role.SUPERADMIN
    return User.telegram_username == identifier


async def issue_tokens(session: AsyncSession, user: User) -> tuple[TokenOut, RefreshToken]:
    s = get_settings()
    raw, token_hash = new_refresh_token()
    rt = RefreshToken(
        user_id=user.id,
        token_hash=token_hash,
        expires_at=utcnow() + timedelta(days=s.refresh_token_ttl_days),
    )
    session.add(rt)
    await session.flush()
    out = TokenOut(
        access_token=create_access_token(user.id),
        refresh_token=raw,
        expires_in=s.access_token_ttl_minutes * 60,
        must_change_password=user.must_change_password,
    )
    return out, rt


async def revoke_all_tokens(session: AsyncSession, user_id: uuid.UUID) -> None:
    await session.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=utcnow())
    )


def _locked_error(user: User) -> AppError:
    assert user.locked_until is not None
    return AppError(
        423,
        ErrorCode.ACCOUNT_LOCKED,
        "Account is temporarily locked after too many failed logins",
        {"locked_until": user.locked_until.isoformat()},
    )


async def login_with_password(session: AsyncSession, username: str, password: str) -> TokenOut:
    s = get_settings()
    now = utcnow()
    identifier = normalize_login(username)

    user = await session.scalar(
        select(User).where(_login_clause(identifier), User.is_active).with_for_update()
    )
    if user is None:
        inactive = await session.scalar(
            select(User)
            .where(_login_clause(identifier), User.is_active.is_(False))
            .order_by(User.deleted_at.desc().nulls_last())
            .limit(1)
        )
        record(
            session,
            "auth.login_failed",
            target_user_id=inactive.id if inactive else None,
            details={"username": identifier, "reason": "inactive" if inactive else "unknown_user"},
        )
        await session.commit()
        if inactive is not None and verify_password(inactive.password_hash, password):
            raise AppError(403, ErrorCode.ACCOUNT_DISABLED, "Account is deactivated")
        raise AppError(401, ErrorCode.INVALID_CREDENTIALS, "Invalid username or password")

    if user.locked_until is not None and user.locked_until > now:
        record(
            session,
            "auth.login_failed",
            target_user_id=user.id,
            details={"username": identifier, "reason": "locked"},
        )
        await session.commit()
        raise _locked_error(user)

    if not verify_password(user.password_hash, password):
        user.failed_login_count += 1
        record(
            session,
            "auth.login_failed",
            target_user_id=user.id,
            details={
                "username": identifier,
                "reason": "bad_password",
                "attempt": user.failed_login_count,
            },
        )
        locked = user.failed_login_count >= s.login_max_attempts
        if locked:
            user.locked_until = now + timedelta(minutes=s.login_lock_minutes)
            user.failed_login_count = 0
            record(
                session,
                "auth.locked",
                target_user_id=user.id,
                details={"locked_until": user.locked_until.isoformat()},
            )
        await session.commit()
        if locked:
            raise _locked_error(user)
        raise AppError(401, ErrorCode.INVALID_CREDENTIALS, "Invalid username or password")

    user.failed_login_count = 0
    user.locked_until = None
    if password_needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
    tokens, _ = await issue_tokens(session, user)
    record(
        session,
        "auth.login",
        actor_id=user.id,
        target_user_id=user.id,
        details={"method": "password"},
    )
    await session.commit()
    return tokens


async def login_with_telegram(session: AsyncSession, init_data: str) -> TokenOut:
    s = get_settings()
    tg = validate_init_data(init_data, s.telegram_bot_token, s.telegram_init_data_max_age_seconds)

    # Once bound, a user is matched only by Telegram user ID.
    user = await session.scalar(
        select(User).where(User.telegram_user_id == tg.id, User.is_active).with_for_update()
    )
    username: str | None = None
    if tg.username:
        try:
            username = normalize_telegram_username(tg.username)
        except AppError:
            username = None

    bound_now = False
    if user is None and username:
        user = await session.scalar(
            select(User)
            .where(
                User.telegram_username == username,
                User.is_active,
                User.telegram_user_id.is_(None),
            )
            .with_for_update()
        )
        if user is not None:
            user.telegram_user_id = tg.id
            bound_now = True

    if user is None:
        match_inactive = [User.telegram_user_id == tg.id]
        if username:
            match_inactive.append(User.telegram_username == username)
        inactive_id = await session.scalar(
            select(User.id).where(or_(*match_inactive), User.is_active.is_(False)).limit(1)
        )
        record(
            session,
            "auth.login_failed",
            target_user_id=inactive_id,
            details={
                "method": "telegram",
                "telegram_user_id": tg.id,
                "username": username,
                "reason": "inactive" if inactive_id else "not_registered",
            },
        )
        await session.commit()
        if inactive_id is not None:
            raise AppError(403, ErrorCode.ACCOUNT_DISABLED, "Account is deactivated")
        raise AppError(
            403, ErrorCode.USER_NOT_REGISTERED, "This Telegram account is not registered"
        )

    tokens, _ = await issue_tokens(session, user)
    if bound_now:
        record(
            session,
            "auth.telegram_bound",
            actor_id=user.id,
            target_user_id=user.id,
            details={"telegram_user_id": tg.id},
        )
    record(
        session,
        "auth.login",
        actor_id=user.id,
        target_user_id=user.id,
        details={"method": "telegram"},
    )
    await session.commit()
    return tokens


async def refresh_tokens(session: AsyncSession, raw_token: str) -> TokenOut:
    now = utcnow()
    rt = await session.scalar(
        select(RefreshToken)
        .where(RefreshToken.token_hash == hash_refresh_token(raw_token))
        .with_for_update()
    )
    if rt is None or rt.revoked_at is not None or rt.expires_at <= now:
        raise AppError(401, ErrorCode.INVALID_REFRESH_TOKEN, "Invalid or expired refresh token")
    user = await session.get(User, rt.user_id)
    rt.revoked_at = now
    if user is None or not user.is_active:
        await session.commit()
        raise AppError(401, ErrorCode.ACCOUNT_DISABLED, "Account is deactivated")
    tokens, new_rt = await issue_tokens(session, user)
    rt.replaced_by = new_rt.id
    await session.commit()
    return tokens


async def logout(
    session: AsyncSession, user: User, raw_token: str | None, all_sessions: bool
) -> None:
    if all_sessions:
        await revoke_all_tokens(session, user.id)
    elif raw_token:
        await session.execute(
            update(RefreshToken)
            .where(
                RefreshToken.token_hash == hash_refresh_token(raw_token),
                RefreshToken.user_id == user.id,
                RefreshToken.revoked_at.is_(None),
            )
            .values(revoked_at=utcnow())
        )
    record(
        session,
        "auth.logout",
        actor_id=user.id,
        target_user_id=user.id,
        details={"all_sessions": all_sessions},
    )
    await session.commit()


def _default_password(user: User) -> str:
    if user.role == Role.SUPERADMIN:
        return get_settings().superadmin_initial_password
    assert user.telegram_username is not None
    return user.telegram_username


def validate_new_password(user: User, new_password: str) -> None:
    if len(new_password) < MIN_PASSWORD_LENGTH:
        raise AppError(
            422,
            ErrorCode.PASSWORD_TOO_SHORT,
            f"Password must be at least {MIN_PASSWORD_LENGTH} characters",
            {"min_length": MIN_PASSWORD_LENGTH},
        )
    forbidden = {SUPERADMIN_USERNAME} if user.role == Role.SUPERADMIN else set()
    if user.telegram_username:
        forbidden.add(user.telegram_username)
    if normalize_login(new_password) in forbidden:
        raise AppError(
            422, ErrorCode.PASSWORD_EQUALS_USERNAME, "Password must not equal the username"
        )


async def change_password(
    session: AsyncSession, user: User, current_password: str, new_password: str
) -> None:
    if not verify_password(user.password_hash, current_password):
        raise AppError(400, ErrorCode.WRONG_CURRENT_PASSWORD, "Current password is incorrect")
    validate_new_password(user, new_password)
    user.password_hash = hash_password(new_password)
    user.must_change_password = False
    record(session, "auth.password_changed", actor_id=user.id, target_user_id=user.id)
    await session.commit()


async def reset_to_default_password(session: AsyncSession, user: User) -> None:
    """Password becomes the default (Telegram username; `superadmin` for the superadmin).

    Everyone except the superadmin must change it at next login. All sessions are revoked.
    Does not commit.
    """
    user.password_hash = hash_password(_default_password(user))
    user.must_change_password = user.role != Role.SUPERADMIN
    user.failed_login_count = 0
    user.locked_until = None
    await revoke_all_tokens(session, user.id)


async def build_me(session: AsyncSession, user: User) -> MeOut:
    perms = await effective_permissions(session, user)
    return MeOut(
        user=UserOut.model_validate(user),
        permissions=sorted(perms),
        manageable_roles=manageable_roles(user.role),
        can_self_reset_password=user.role in SELF_RESET_ROLES and "users.reset_password" in perms,
    )
