import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.deps import SessionDep, require_role
from app.models import Role, User
from app.schemas.audit import AuditLogOut, AuditLogPage, AuditUserRef
from app.services.audit_service import list_audit_logs

router = APIRouter(prefix="/audit-logs", tags=["audit"])

AuditViewer = Annotated[User, Depends(require_role(Role.SUPERADMIN, Role.GENERAL_MANAGER))]


def _ref(user: User | None) -> AuditUserRef | None:
    if user is None:
        return None
    return AuditUserRef(
        id=user.id,
        full_name=user.full_name,
        role=user.role,
        telegram_username=user.telegram_username,
    )


@router.get("", response_model=AuditLogPage)
async def get_audit_logs(
    _: AuditViewer,
    session: SessionDep,
    action: Annotated[str | None, Query(max_length=64)] = None,
    actor_id: uuid.UUID | None = None,
    target_user_id: uuid.UUID | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 50,
) -> AuditLogPage:
    rows, total = await list_audit_logs(
        session,
        action=action,
        actor_id=actor_id,
        target_user_id=target_user_id,
        date_from=date_from,
        date_to=date_to,
        page=page,
        page_size=page_size,
    )
    return AuditLogPage(
        items=[
            AuditLogOut(
                id=log.id,
                action=log.action,
                actor=_ref(actor),
                target=_ref(target),
                details=log.details,
                created_at=log.created_at,
            )
            for log, actor, target in rows
        ],
        total=total,
        page=page,
        page_size=page_size,
    )
