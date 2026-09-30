"""In-app notifications (the bell) and their Telegram delivery status.

One row per recipient, inserted in the same transaction as the action that caused it (e.g.
finishing step 2). Telegram delivery happens after commit and only updates `telegram_status`.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, utcnow

NOTIFICATION_TYPES = ("production.processing_finished", "production.completed")
TELEGRAM_STATUSES = ("pending", "sent", "failed", "not_linked", "bot_off")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (
        CheckConstraint(_in("type", NOTIFICATION_TYPES), name="type"),
        CheckConstraint(_in("telegram_status", TELEGRAM_STATUSES), name="telegram_status"),
        Index("ix_notifications_user_read_created", "user_id", "read_at", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    type: Mapped[str] = mapped_column(String(64))
    # The record it is about (e.g. "production_batch" + its id). No FK, like audit_logs.
    entity_type: Mapped[str] = mapped_column(String(32))
    entity_id: Mapped[uuid.UUID] = mapped_column()
    # Figures for the message: code, counts, planned/actual, comment, actor_id, repeat.
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    telegram_status: Mapped[str] = mapped_column(
        String(16), default="pending", server_default=text("'pending'")
    )
    telegram_error: Mapped[str | None] = mapped_column(Text)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TelegramLinkToken(Base):
    """One-time token behind the superadmin's "Link Telegram" deep link (/start link_<token>)."""

    __tablename__ = "telegram_link_tokens"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    # SHA-256 hex digest of the raw token; the raw token is never stored.
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
