"""Business info printed on documents (delivery notes, later invoices). One row, id 1."""

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    LargeBinary,
    SmallInteger,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, utcnow

BUSINESS_NAME_MAX_LENGTH = 200
BUSINESS_ADDRESS_MAX_LENGTH = 500
BUSINESS_FOOTER_MAX_LENGTH = 300
LOGO_MIMES = ("image/png", "image/jpeg")


class BusinessSettings(Base):
    __tablename__ = "business_settings"
    __table_args__ = (
        CheckConstraint("id = 1", name="single_row"),
        CheckConstraint("(logo IS NULL) = (logo_mime IS NULL)", name="logo_mime"),
    )

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, default=1)
    name_km: Mapped[str] = mapped_column(String(BUSINESS_NAME_MAX_LENGTH))
    name_en: Mapped[str] = mapped_column(String(BUSINESS_NAME_MAX_LENGTH))
    address_km: Mapped[str | None] = mapped_column(String(BUSINESS_ADDRESS_MAX_LENGTH))
    address_en: Mapped[str | None] = mapped_column(String(BUSINESS_ADDRESS_MAX_LENGTH))
    # Normalized (core/phones.py); shown with format_phone.
    phone: Mapped[str | None] = mapped_column(String(32))
    footer_note_km: Mapped[str | None] = mapped_column(String(BUSINESS_FOOTER_MAX_LENGTH))
    footer_note_en: Mapped[str | None] = mapped_column(String(BUSINESS_FOOTER_MAX_LENGTH))
    # PNG or JPEG, stored resized to at most 400 px wide.
    logo: Mapped[bytes | None] = mapped_column(LargeBinary, deferred=True)
    logo_mime: Mapped[str | None] = mapped_column(String(16))
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )
