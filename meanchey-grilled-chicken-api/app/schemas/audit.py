import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel

from app.schemas.common import UserRef


class AuditEntityRef(BaseModel):
    """Non-user record an entry is about. `name` is the current name, else the one logged."""

    type: str
    id: uuid.UUID
    name: str | None


class AuditLogOut(BaseModel):
    id: int
    action: str
    actor: UserRef | None
    target: UserRef | None
    entity: AuditEntityRef | None
    details: dict[str, Any]
    created_at: datetime


class AuditLogPage(BaseModel):
    items: list[AuditLogOut]
    total: int
    page: int
    page_size: int
