import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models import AuditLog, User


def record(
    session: AsyncSession,
    action: str,
    *,
    actor_id: uuid.UUID | None = None,
    target_user_id: uuid.UUID | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    """Add an audit entry to the current transaction (the caller commits)."""
    session.add(
        AuditLog(
            action=action,
            actor_id=actor_id,
            target_user_id=target_user_id,
            details=details or {},
        )
    )


async def list_audit_logs(
    session: AsyncSession,
    *,
    action: str | None,
    actor_id: uuid.UUID | None,
    target_user_id: uuid.UUID | None,
    date_from: datetime | None,
    date_to: datetime | None,
    page: int,
    page_size: int,
) -> tuple[list[tuple], int]:
    actor = aliased(User)
    target = aliased(User)
    conditions = []
    if action:
        conditions.append(AuditLog.action == action)
    if actor_id:
        conditions.append(AuditLog.actor_id == actor_id)
    if target_user_id:
        conditions.append(AuditLog.target_user_id == target_user_id)
    if date_from:
        conditions.append(AuditLog.created_at >= date_from)
    if date_to:
        conditions.append(AuditLog.created_at < date_to)

    total = await session.scalar(select(func.count(AuditLog.id)).where(*conditions)) or 0
    rows = (
        await session.execute(
            select(AuditLog, actor, target)
            .outerjoin(actor, AuditLog.actor_id == actor.id)
            .outerjoin(target, AuditLog.target_user_id == target.id)
            .where(*conditions)
            .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    return [tuple(r) for r in rows], total
