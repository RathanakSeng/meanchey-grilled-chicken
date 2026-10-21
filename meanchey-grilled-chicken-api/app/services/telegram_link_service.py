"""The superadmin links its Telegram account with a one-time deep link (it has no username).

`create_link` stores a random token hashed (SHA-256, like refresh tokens) with a 10-minute expiry
and returns `https://t.me/<bot>?start=link_<token>`. The bot's `/start link_<token>` calls
`consume`: a valid, unexpired, unused token binds the sender's Telegram id to the superadmin,
unless that id already belongs to another active user. Every failure looks the same to the
sender (no hint about why or about the account's role).

Once linked, the superadmin receives production alerts on Telegram. Mini App sign-in matches
users by their bound Telegram id first, so opening the Mini App from that account also signs the
superadmin in.

Everyone else is bound by Telegram username, either at Mini App sign-in
(`auth_service.login_with_telegram`) or when they press Start in the bot (`bind_on_start`, the
same rule), so alerts and attendance reminders reach them without opening the app first.
"""

import secrets
from datetime import timedelta

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.core.security import hash_token
from app.core.usernames import normalize_telegram_username
from app.models import Language, Role, TelegramLinkToken, User, utcnow
from app.schemas.notification import TelegramLinkOut
from app.services.audit_service import record

TOKEN_TTL = timedelta(minutes=10)
START_PREFIX = "link_"


async def create_link(session: AsyncSession, user: User, bot_username: str) -> TelegramLinkOut:
    raw = secrets.token_urlsafe(24)  # 32 chars of [A-Za-z0-9_-]; /start allows up to 64
    now = utcnow()
    expires_at = now + TOKEN_TTL
    session.add(
        TelegramLinkToken(
            user_id=user.id, token_hash=hash_token(raw), created_at=now, expires_at=expires_at
        )
    )
    await session.commit()
    return TelegramLinkOut(
        url=f"https://t.me/{bot_username}?start={START_PREFIX}{raw}", expires_at=expires_at
    )


async def unlink(session: AsyncSession, user: User) -> None:
    if user.telegram_user_id is None:
        return
    user.telegram_user_id = None
    record(session, "profile.telegram_unlink", actor_id=user.id, target_user_id=user.id)
    await session.commit()


async def consume(session: AsyncSession, raw: str, telegram_user_id: int) -> Language | None:
    """Bind `telegram_user_id` to the token's user. The user's language on success, else None."""
    now = utcnow()
    token = await session.scalar(
        select(TelegramLinkToken)
        .where(TelegramLinkToken.token_hash == hash_token(raw))
        .with_for_update()
    )
    if token is None or token.used_at is not None or token.expires_at <= now:
        return None
    user = await session.get(User, token.user_id, with_for_update=True)
    if user is None or not user.is_active or user.role != Role.SUPERADMIN:
        return None
    taken = await session.scalar(
        select(User.id).where(
            User.telegram_user_id == telegram_user_id, User.is_active, User.id != user.id
        )
    )
    if taken is not None:
        return None
    token.used_at = now
    # Any other unused token of this user is spent too: one link per request.
    await session.execute(
        update(TelegramLinkToken)
        .where(TelegramLinkToken.user_id == user.id, TelegramLinkToken.used_at.is_(None))
        .values(used_at=now)
    )
    user.telegram_user_id = telegram_user_id
    record(session, "profile.telegram_link", actor_id=user.id, target_user_id=user.id)
    await session.commit()
    return user.language


async def bind_on_start(
    session: AsyncSession, telegram_user_id: int, telegram_username: str | None
) -> bool:
    """`/start`: bind this Telegram id to the active user with the same (normalized) Telegram
    username, exactly like Mini App sign-in. Nothing happens when an active user is already bound
    to this id, when the matching account is bound to another id, or for the superadmin (it links
    with its one-time link). True when it bound an account."""
    if not telegram_username:
        return False
    try:
        username = normalize_telegram_username(telegram_username)
    except AppError:
        return False
    bound = await session.scalar(
        select(User.id).where(User.telegram_user_id == telegram_user_id, User.is_active)
    )
    if bound is not None:
        return False
    user = await session.scalar(
        select(User)
        .where(
            User.telegram_username == username,
            User.is_active,
            User.telegram_user_id.is_(None),
            User.role != Role.SUPERADMIN,
        )
        .with_for_update()
    )
    if user is None:
        return False
    user.telegram_user_id = telegram_user_id
    record(
        session,
        "auth.telegram_bound",
        actor_id=user.id,
        target_user_id=user.id,
        details={"telegram_user_id": telegram_user_id, "via": "bot_start"},
    )
    try:
        await session.commit()
    except IntegrityError:  # the id was bound concurrently (one active user per Telegram id)
        await session.rollback()
        return False
    return True
