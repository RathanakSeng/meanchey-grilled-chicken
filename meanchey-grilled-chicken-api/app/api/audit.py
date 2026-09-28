import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.deps import SessionDep, require_role
from app.models import AuditLog, Role, User
from app.schemas.audit import AuditEntityRef, AuditLogOut, AuditLogPage
from app.schemas.common import UserRef
from app.services.audit_service import entity_names, list_audit_logs

router = APIRouter(prefix="/audit-logs", tags=["audit"])

AuditViewer = Annotated[User, Depends(require_role(Role.SUPERADMIN, Role.GENERAL_MANAGER))]


def _ref(user: User | None) -> UserRef | None:
    return UserRef.model_validate(user) if user is not None else None


def _entity(log: AuditLog, names: dict[uuid.UUID, str]) -> AuditEntityRef | None:
    if log.entity_type is None or log.entity_id is None:
        return None
    return AuditEntityRef(
        type=log.entity_type,
        id=log.entity_id,
        name=names.get(log.entity_id) or log.details.get("name"),
    )


@router.get("", response_model=AuditLogPage)
async def get_audit_logs(
    viewer: AuditViewer,
    session: SessionDep,
    action: Annotated[str | None, Query(max_length=64)] = None,
    actor_id: uuid.UUID | None = None,
    target_user_id: uuid.UUID | None = None,
    entity_type: Annotated[str | None, Query(max_length=32)] = None,
    entity_id: uuid.UUID | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 50,
) -> AuditLogPage:
    rows, total = await list_audit_logs(
        session,
        viewer=viewer,
        action=action,
        actor_id=actor_id,
        target_user_id=target_user_id,
        entity_type=entity_type,
        entity_id=entity_id,
        date_from=date_from,
        date_to=date_to,
        page=page,
        page_size=page_size,
    )
    names = await entity_names(session, [log for log, _, _ in rows])
    return AuditLogPage(
        items=[
            AuditLogOut(
                id=log.id,
                action=log.action,
                actor=_ref(actor),
                target=_ref(target),
                entity=_entity(log, names),
                details=log.details,
                created_at=log.created_at,
            )
            for log, actor, target in rows
        ],
        total=total,
        page=page,
        page_size=page_size,
    )
