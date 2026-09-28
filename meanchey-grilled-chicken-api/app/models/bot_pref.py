from datetime import datetime

from sqlalchemy import BigInteger, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, utcnow
from app.models.enums import Language, language_type


class BotPref(Base):
    """Bot language for Telegram accounts (registered or not)."""

    __tablename__ = "bot_prefs"

    telegram_user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    language: Mapped[Language] = mapped_column(language_type)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, server_default=func.now()
    )
