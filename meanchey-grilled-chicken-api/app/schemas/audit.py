import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel

from app.models import Role


class AuditUserRef(BaseModel):
    id: uuid.UUID
    full_name: str
    role: Role
    telegram_username: str | None


class AuditLogOut(BaseModel):
    id: int
    action: str
    actor: AuditUserRef | None
    target: AuditUserRef | None
    details: dict[str, Any]
    created_at: datetime


class AuditLogPage(BaseModel):
    items: list[AuditLogOut]
    total: int
    page: int
    page_size: int
