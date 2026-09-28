"""Business partners: suppliers and customers. Same shape, separate tables."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, func, text
from sqlalchemy.orm import Mapped, declared_attr, mapped_column

from app.models.base import Base, utcnow

PARTNER_NAME_MAX_LENGTH = 150
PARTNER_LOCATION_MAX_LENGTH = 255
PARTNER_PHONE_MAX_LENGTH = 20


class PartnerMixin:
    """Columns and indexes shared by every partner table."""

    @declared_attr.directive
    def __table_args__(cls) -> tuple:
        table = cls.__tablename__
        return (
            Index(f"ix_{table}_name_lower", func.lower(text("name"))),
            # A phone number identifies one active partner per table.
            Index(
                f"uq_{table}_active_phone",
                "phone",
                unique=True,
                postgresql_where=text("is_active AND phone IS NOT NULL"),
            ),
        )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(PARTNER_NAME_MAX_LENGTH))
    location: Mapped[str | None] = mapped_column(String(PARTNER_LOCATION_MAX_LENGTH))
    phone: Mapped[str | None] = mapped_column(String(PARTNER_PHONE_MAX_LENGTH))
    is_active: Mapped[bool] = mapped_column(default=True, server_default=text("true"))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, server_default=func.now()
    )


class Supplier(PartnerMixin, Base):
    __tablename__ = "suppliers"


class Customer(PartnerMixin, Base):
    __tablename__ = "customers"
