"""Production alerts: stored first (the bell), sent to Telegram after commit.

- **Recipients:** active users holding `production_plan.view` (effective permissions: granted,
  permission active, still assignable to their role) and the superadmin, who holds everything
  implicitly. Staff can't hold it. The actor is included when they qualify.
- **Creation:** `notify()` inserts one row per recipient in the caller's transaction (e.g. the step
  2 Finish), so an alert exists exactly when the action committed. The new ids are queued on the
  session (`session.info`); the router hands them to a background task after the response
  (`take_queued()` + `app.bot.notify.deliver`). Telegram never blocks or fails the action.
- **Redaction:** the payload stores `actor_id`; the API serializes it as a `UserRef` for the
  recipient viewing it, so the superadmin reads as "System" to everyone else.
"""

import uuid
from typing import Any

from sqlalchemy import String, and_, any_, cast, exists, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, ErrorCode
from app.models import Notification, Permission, Role, User, UserPermission, utcnow
from app.schemas.common import UserRef
from app.schemas.notification import NotificationOut, NotificationPage

ALERT_PERMISSION = "production_plan.view"
PROCESSING_FINISHED = "production.processing_finished"
COMPLETED = "production.completed"
_QUEUE_KEY = "queued_notifications"


async def recipients(session: AsyncSession) -> list[User]:
    """Active users who hold `production_plan.view` (same rule as effective permissions)."""
    holds_view = exists(
        select(UserPermission.user_id)
        .join(Permission, Permission.code == UserPermission.permission_code)
        .where(
            UserPermission.user_id == User.id,
            UserPermission.permission_code == ALERT_PERMISSION,
            Permission.is_active,
            cast(User.role, String) == any_(Permission.assignable_to),
        )
    )
    # The superadmin implicitly holds every active permission.
    superadmin_holds = and_(
        User.role == Role.SUPERADMIN,
        exists(
            select(Permission.code).where(Permission.code == ALERT_PERMISSION, Permission.is_active)
        ),
    )
    stmt = (
        select(User)
        .where(User.is_active, or_(superadmin_holds, holds_view))
        .order_by(User.created_at, User.id)
    )
    return list(await session.scalars(stmt))


async def notify(
    session: AsyncSession,
    type_: str,
    *,
    entity_type: str,
    entity_id: uuid.UUID,
    payload: dict[str, Any],
) -> list[uuid.UUID]:
    """Insert one notification per recipient (not committed) and queue them for Telegram.

    `payload.repeat` is true when this entity already had an alert of this type (e.g. step 2
    finished again after a reopen)."""
    repeat = bool(
        await session.scalar(
            select(
                exists().where(
                    Notification.type == type_,
                    Notification.entity_type == entity_type,
                    Notification.entity_id == entity_id,
                )
            )
        )
    )
    now = utcnow()
    rows = [
        Notification(
            id=uuid.uuid4(),
            user_id=user.id,
            type=type_,
            entity_type=entity_type,
            entity_id=entity_id,
            payload={**payload, "repeat": repeat},
            created_at=now,
            telegram_status="pending",
        )
        for user in await recipients(session)
    ]
    session.add_all(rows)
    ids = [r.id for r in rows]
    session.info.setdefault(_QUEUE_KEY, []).extend(ids)
    return ids


def take_queued(session: AsyncSession) -> list[uuid.UUID]:
    """The ids created in this session since the last call (to send after commit)."""
    return session.info.pop(_QUEUE_KEY, [])


def discard_queued(session: AsyncSession) -> None:
    session.info.pop(_QUEUE_KEY, None)


# --- The bell ------------------------------------------------------------------------------------


async def _unread_count(session: AsyncSession, user: User) -> int:
    return (
        await session.scalar(
            select(func.count(Notification.id)).where(
                Notification.user_id == user.id, Notification.read_at.is_(None)
            )
        )
        or 0
    )


async def _actors(session: AsyncSession, rows: list[Notification]) -> dict[uuid.UUID, User]:
    ids = set()
    for r in rows:
        actor_id = r.payload.get("actor_id")
        if actor_id:
            ids.add(uuid.UUID(actor_id))
    if not ids:
        return {}
    return {u.id: u for u in await session.scalars(select(User).where(User.id.in_(ids)))}


def _out(row: Notification, actors: dict[uuid.UUID, User]) -> NotificationOut:
    payload = {k: v for k, v in row.payload.items() if k != "actor_id"}
    actor_id = row.payload.get("actor_id")
    actor = actors.get(uuid.UUID(actor_id)) if actor_id else None
    return NotificationOut(
        id=row.id,
        type=row.type,
        entity_type=row.entity_type,
        entity_id=row.entity_id,
        payload=payload,
        actor=UserRef.model_validate(actor) if actor else None,
        created_at=row.created_at,
        read_at=row.read_at,
        telegram_status=row.telegram_status,
    )


async def list_own(
    session: AsyncSession, user: User, *, unread_only: bool, page: int, page_size: int
) -> NotificationPage:
    conditions = [Notification.user_id == user.id]
    if unread_only:
        conditions.append(Notification.read_at.is_(None))
    total = await session.scalar(select(func.count(Notification.id)).where(*conditions)) or 0
    rows = list(
        await session.scalars(
            select(Notification)
            .where(*conditions)
            .order_by(Notification.created_at.desc(), Notification.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    )
    actors = await _actors(session, rows)
    return NotificationPage(
        items=[_out(r, actors) for r in rows],
        total=total,
        page=page,
        page_size=page_size,
        unread_count=await _unread_count(session, user),
    )


async def mark_read(
    session: AsyncSession, user: User, notification_id: uuid.UUID
) -> NotificationOut:
    row = await session.get(Notification, notification_id)
    # Someone else's notification is "not found", not "forbidden".
    if row is None or row.user_id != user.id:
        raise AppError(404, ErrorCode.NOTIFICATION_NOT_FOUND, "Notification not found")
    if row.read_at is None:
        row.read_at = utcnow()
        await session.commit()
    return _out(row, await _actors(session, [row]))


async def mark_all_read(session: AsyncSession, user: User) -> int:
    result = await session.execute(
        update(Notification)
        .where(Notification.user_id == user.id, Notification.read_at.is_(None))
        .values(read_at=utcnow())
    )
    await session.commit()
    return result.rowcount or 0


async def unread_count(session: AsyncSession, user: User) -> int:
    return await _unread_count(session, user)
