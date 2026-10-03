"""Notifications (the bell) and the superadmin's Telegram link."""

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel

from app.schemas.common import UserRef

NotificationType = Literal[
    "production.processing_finished",
    "production.completed",
    "order.delivering",
    "order.delivered",
    "order.return_pending",
    "order.returns_reviewed",
]
TelegramStatus = Literal["pending", "sent", "failed", "not_linked", "bot_off"]


class NotificationOut(BaseModel):
    id: uuid.UUID
    type: NotificationType
    entity_type: str
    entity_id: uuid.UUID
    # Figures for the text, e.g. {code, quantity, wings, thighs, repeat} or {code, matches,
    # planned_big, planned_small, actual_big, actual_small, comment, repeat}.
    payload: dict[str, Any]
    # Who finished the step ("System" for hidden accounts).
    actor: UserRef | None
    created_at: datetime
    read_at: datetime | None
    telegram_status: TelegramStatus


class NotificationPage(BaseModel):
    items: list[NotificationOut]
    total: int
    page: int
    page_size: int
    unread_count: int


class ReadAllOut(BaseModel):
    updated: int
    unread_count: int


class TelegramLinkOut(BaseModel):
    # https://t.me/<bot>?start=link_<token>; valid once, until expires_at.
    url: str
    expires_at: datetime
