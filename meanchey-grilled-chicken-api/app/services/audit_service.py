import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models import AuditLog, Customer, Role, Supplier, User

# entity_type -> table holding records of that type (for the entity name in listings).
ENTITY_MODELS: dict[str, type[Supplier] | type[Customer]] = {
    "supplier": Supplier,
    "customer": Customer,
}


def record(
    session: AsyncSession,
    action: str,
    *,
    actor_id: uuid.UUID | None = None,
    target_user_id: uuid.UUID | None = None,
    entity_type: str | None = None,
    entity_id: uuid.UUID | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    """Add an audit entry to the current transaction (the caller commits)."""
    session.add(
        AuditLog(
            action=action,
            actor_id=actor_id,
            target_user_id=target_user_id,
            entity_type=entity_type,
            entity_id=entity_id,
            details=details or {},
        )
    )


# Detailed permission changes are superadmin business; other viewers see `feature.set` instead.
PERMISSION_ACTIONS = ("permission.grant", "permission.revoke")


async def list_audit_logs(
    session: AsyncSession,
    *,
    viewer: User,
    action: str | None,
    actor_id: uuid.UUID | None,
    target_user_id: uuid.UUID | None,
    entity_type: str | None,
    entity_id: uuid.UUID | None,
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
    if entity_type:
        conditions.append(AuditLog.entity_type == entity_type)
    if entity_id:
        conditions.append(AuditLog.entity_id == entity_id)
    if date_from:
        conditions.append(AuditLog.created_at >= date_from)
    if date_to:
        conditions.append(AuditLog.created_at < date_to)
    if viewer.role != Role.SUPERADMIN:
        # Hidden account: nothing it did, nothing about it, and no detailed permission entries.
        # Entries with no actor (e.g. failed sign-ins) stay.
        hidden_ids = select(User.id).where(User.role == Role.SUPERADMIN).scalar_subquery()
        conditions += [
            or_(AuditLog.actor_id.is_(None), AuditLog.actor_id.not_in(hidden_ids)),
            or_(AuditLog.target_user_id.is_(None), AuditLog.target_user_id.not_in(hidden_ids)),
            AuditLog.action.not_in(PERMISSION_ACTIONS),
        ]

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


async def entity_names(session: AsyncSession, logs: list[AuditLog]) -> dict[uuid.UUID, str]:
    """Current names of the records referenced by `logs`: one query per entity type."""
    ids_by_type: dict[str, set[uuid.UUID]] = {}
    for log in logs:
        if log.entity_type in ENTITY_MODELS and log.entity_id is not None:
            ids_by_type.setdefault(log.entity_type, set()).add(log.entity_id)
    names: dict[uuid.UUID, str] = {}
    for entity_type, ids in ids_by_type.items():
        model = ENTITY_MODELS[entity_type]
        rows = await session.execute(select(model.id, model.name).where(model.id.in_(ids)))
        names.update({row_id: name for row_id, name in rows})
    return names
