import uuid
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, ErrorCode
from app.core.security import hash_password
from app.core.usernames import normalize_telegram_username
from app.models import Role, User, utcnow
from app.permissions.hierarchy import MANAGEABLE_ROLES, ensure_can_manage, ensure_can_manage_role
from app.permissions.service import grant_defaults, reset_to_role_defaults
from app.schemas.user import (
    ProfileUpdate,
    RoleChange,
    UserCreate,
    UserStatus,
    UserUpdate,
    normalize_position,
)
from app.services.audit_service import record
from app.services.auth_service import SELF_RESET_ROLES, reset_to_default_password, revoke_all_tokens
from app.services.redaction import hides_user
from app.services.role_limit_service import ensure_slot


def _duplicate_username_error() -> AppError:
    return AppError(
        409, ErrorCode.DUPLICATE_TELEGRAM_USERNAME, "Telegram username is already in use"
    )


async def _flush_or_conflict(session: AsyncSession) -> None:
    """Flush, translating DB-level uniqueness violations into API errors."""
    try:
        await session.flush()
    except IntegrityError as e:
        await session.rollback()
        msg = str(e.orig)
        if "uq_users_active_telegram_username" in msg:
            raise _duplicate_username_error() from e
        raise


async def get_user_or_404(
    session: AsyncSession, user_id: uuid.UUID, viewer: User | None = None
) -> User:
    """Load a user. Hidden accounts (see services/redaction.py) are "not found" for `viewer`.

    Pass the acting user as `viewer` on every per-user endpoint, so a lookup by id can't be used
    to confirm that a hidden account exists (a 403 FORBIDDEN_SCOPE would).
    """
    user = await session.get(User, user_id)
    if user is None or (viewer is not None and hides_user(user, viewer)):
        raise AppError(404, ErrorCode.USER_NOT_FOUND, "User not found")
    return user


async def _username_taken(
    session: AsyncSession, username: str, exclude_id: uuid.UUID | None = None
) -> bool:
    stmt = select(User.id).where(User.telegram_username == username, User.is_active)
    if exclude_id is not None:
        stmt = stmt.where(User.id != exclude_id)
    return (await session.scalar(stmt.limit(1))) is not None


def _check_position(role: Role, position: str | None) -> None:
    """Position is a descriptive label: only its presence depends on the role."""
    if role == Role.STAFF and position is None:
        raise AppError(422, ErrorCode.POSITION_REQUIRED, "Staff must have a position")
    if role != Role.STAFF and position is not None:
        raise AppError(422, ErrorCode.POSITION_NOT_ALLOWED, "Only staff have a position")


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


async def list_users(
    session: AsyncSession,
    actor: User,
    *,
    role: Role | None,
    position: str | None,
    status: UserStatus,
    q: str | None,
    page: int,
    page_size: int,
) -> tuple[list[User], int]:
    roles = MANAGEABLE_ROLES[actor.role]
    if not roles:
        return [], 0
    conditions: list[Any] = [User.role.in_(roles)]
    if role is not None:
        conditions.append(User.role == role)
    position = normalize_position(position)
    if position is not None:
        conditions.append(func.lower(User.position) == position.lower())
    if status == "active":
        conditions.append(User.is_active)
    elif status == "inactive":
        conditions.append(User.is_active.is_(False))
    if q and q.strip():
        pattern = f"%{_escape_like(q.strip())}%"
        conditions.append(
            or_(
                User.full_name.ilike(pattern, escape="\\"),
                User.telegram_username.ilike(pattern, escape="\\"),
                User.phone.ilike(pattern, escape="\\"),
                User.position.ilike(pattern, escape="\\"),
            )
        )
    total = await session.scalar(select(func.count(User.id)).where(*conditions)) or 0
    items = await session.scalars(
        select(User)
        .where(*conditions)
        .order_by(User.created_at.desc(), User.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return list(items), total


async def list_positions(session: AsyncSession, actor: User) -> list[str]:
    """Distinct positions (case-insensitive) of active users in the actor's scope, sorted.

    For each case-insensitive group, the most used spelling wins (ties: alphabetical).
    """
    roles = MANAGEABLE_ROLES[actor.role]
    if not roles:
        return []
    key = func.lower(User.position)
    rows = await session.execute(
        select(key.label("key"), User.position, func.count().label("n"))
        .where(User.role.in_(roles), User.is_active, User.position.is_not(None))
        .group_by(key, User.position)
    )
    best: dict[str, tuple[int, str]] = {}
    for group, spelling, n in rows:
        current = best.get(group)
        if current is None or (-n, spelling) < (-current[0], current[1]):
            best[group] = (n, spelling)
    return sorted((spelling for _, spelling in best.values()), key=str.casefold)


async def create_user(session: AsyncSession, actor: User, data: UserCreate) -> User:
    ensure_can_manage_role(actor, data.role)
    _check_position(data.role, data.position)
    username = normalize_telegram_username(data.telegram_username)
    if await _username_taken(session, username):
        raise _duplicate_username_error()
    # Last: locks the role's limit row until commit (concurrent creates take turns).
    await ensure_slot(session, data.role)

    user = User(
        role=data.role,
        position=data.position,
        full_name=data.full_name.strip(),
        phone=data.phone,
        telegram_username=username,
        # Initial password is the Telegram username; it must be changed on first login.
        password_hash=hash_password(username),
        must_change_password=True,
        language=data.language,
        creator=actor,
    )
    session.add(user)
    await _flush_or_conflict(session)
    defaults = await grant_defaults(session, actor, user)
    record(
        session,
        "user.create",
        actor_id=actor.id,
        target_user_id=user.id,
        details={
            "role": user.role.value,
            "position": user.position,
            "telegram_username": username,
            "default_permissions": defaults,
        },
    )
    await session.commit()
    return user


async def update_user(session: AsyncSession, actor: User, target: User, data: UserUpdate) -> User:
    ensure_can_manage(actor, target)
    fields = data.model_fields_set
    changes: dict[str, list[Any]] = {}

    def _set(attr: str, value: Any) -> None:
        old = getattr(target, attr)
        if old != value:
            changes[attr] = [str(old) if old is not None else None, str(value) if value else None]
            setattr(target, attr, value)

    if "full_name" in fields and data.full_name is not None:
        _set("full_name", data.full_name.strip())
    if "phone" in fields:
        _set("phone", data.phone)
    if "language" in fields and data.language is not None:
        _set("language", data.language)
    if "position" in fields:
        _check_position(target.role, data.position)
        _set("position", data.position)
    if "telegram_username" in fields and data.telegram_username is not None:
        username = normalize_telegram_username(data.telegram_username)
        if username != target.telegram_username:
            if target.is_active and await _username_taken(session, username, exclude_id=target.id):
                raise _duplicate_username_error()
            _set("telegram_username", username)
            # A new username may belong to a different Telegram account: drop the binding.
            target.telegram_user_id = None

    if changes:
        await _flush_or_conflict(session)
        record(
            session,
            "user.update",
            actor_id=actor.id,
            target_user_id=target.id,
            details={"changes": changes},
        )
        await session.commit()
    return target


async def change_role(session: AsyncSession, actor: User, target: User, data: RoleChange) -> User:
    """Promote or demote `target` to another role the actor manages.

    The actor must manage both the current and the new role (general manager: supervisor <-> staff;
    superadmin: general manager / supervisor / staff), so supervisors can't change roles and nobody
    changes their own. The user's access is replaced by the new role's defaults; the general
    manager can adjust it afterwards with feature levels.
    """
    ensure_can_manage(actor, target)
    ensure_can_manage_role(actor, data.role)
    if data.role == target.role:
        if data.position is not None and data.position != target.position:
            raise AppError(
                422, ErrorCode.VALIDATION_ERROR, "Use the user edit to change the position"
            )
        return target
    _check_position(data.role, data.position)
    if target.is_active:
        # Only the new role needs a free slot; leaving the old one frees a slot there.
        await ensure_slot(session, data.role)

    old_role, old_position = target.role, target.position
    target.role = data.role
    target.position = data.position
    await _flush_or_conflict(session)
    added, removed = await reset_to_role_defaults(session, actor, target)
    record(
        session,
        "user.role_change",
        actor_id=actor.id,
        target_user_id=target.id,
        details={
            "from": old_role.value,
            "to": target.role.value,
            "position_from": old_position,
            "position_to": target.position,
            "permissions_added": added,
            "permissions_removed": removed,
        },
    )
    await session.commit()
    return target


async def deactivate_user(session: AsyncSession, actor: User, target: User) -> User:
    ensure_can_manage(actor, target)
    if not target.is_active:
        return target
    target.is_active = False
    target.deleted_at = utcnow()
    await revoke_all_tokens(session, target.id)
    record(session, "user.deactivate", actor_id=actor.id, target_user_id=target.id)
    await session.commit()
    return target


async def reactivate_user(session: AsyncSession, actor: User, target: User) -> User:
    ensure_can_manage(actor, target)
    if target.is_active:
        return target
    if target.telegram_username and await _username_taken(
        session, target.telegram_username, exclude_id=target.id
    ):
        raise _duplicate_username_error()
    if target.telegram_user_id is not None:
        bound_elsewhere = await session.scalar(
            select(User.id)
            .where(
                User.telegram_user_id == target.telegram_user_id,
                User.is_active,
                User.id != target.id,
            )
            .limit(1)
        )
        if bound_elsewhere is not None:
            target.telegram_user_id = None
    await ensure_slot(session, target.role)
    target.is_active = True
    target.deleted_at = None
    target.failed_login_count = 0
    target.locked_until = None
    await _flush_or_conflict(session)
    record(session, "user.reactivate", actor_id=actor.id, target_user_id=target.id)
    await session.commit()
    return target


async def reset_password(session: AsyncSession, actor: User, target: User) -> None:
    ensure_can_manage(actor, target)
    if not target.is_active:
        raise AppError(409, ErrorCode.USER_INACTIVE, "User is deactivated")
    await reset_to_default_password(session, target)
    record(session, "user.password_reset", actor_id=actor.id, target_user_id=target.id)
    await session.commit()


async def self_reset_password(session: AsyncSession, user: User) -> None:
    if user.role not in SELF_RESET_ROLES:
        raise AppError(403, ErrorCode.FORBIDDEN_ROLE, "Your role cannot do this")
    await reset_to_default_password(session, user)
    record(session, "user.password_self_reset", actor_id=user.id, target_user_id=user.id)
    await session.commit()


async def update_profile(session: AsyncSession, user: User, data: ProfileUpdate) -> User:
    fields = data.model_fields_set
    changes: dict[str, list[Any]] = {}
    for attr in ("full_name", "phone", "language"):
        if attr not in fields:
            continue
        value = getattr(data, attr)
        if attr != "phone" and value is None:
            continue
        if attr == "full_name":
            value = value.strip()
        old = getattr(user, attr)
        if old != value:
            changes[attr] = [str(old) if old is not None else None, str(value) if value else None]
            setattr(user, attr, value)
    if changes:
        record(
            session,
            "profile.update",
            actor_id=user.id,
            target_user_id=user.id,
            details={"changes": changes},
        )
        await session.commit()
    return user
