"""Business info (Settings → Business info), printed on delivery notes."""

import re
from datetime import datetime
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

from app.models.business import (
    BUSINESS_ADDRESS_MAX_LENGTH,
    BUSINESS_FOOTER_MAX_LENGTH,
    BUSINESS_NAME_MAX_LENGTH,
)
from app.schemas.common import UserRef
from app.schemas.partner import PHONE_INPUT_MAX_LENGTH

_SPACES = re.compile(r"[^\S\n]+")


def _required(value: str) -> str:
    value = _SPACES.sub(" ", value).strip()
    if not value:
        raise ValueError("Name is required")
    return value


def _optional(value: str | None) -> str | None:
    """Trim each line; empty means "not set". Line breaks are kept (addresses)."""
    if value is None:
        return None
    lines = [_SPACES.sub(" ", line).strip() for line in value.strip().splitlines()]
    value = "\n".join(line for line in lines if line)
    return value or None


Name = Annotated[str, Field(max_length=BUSINESS_NAME_MAX_LENGTH), AfterValidator(_required)]
Address = Annotated[
    str | None, Field(max_length=BUSINESS_ADDRESS_MAX_LENGTH), AfterValidator(_optional)
]
Footer = Annotated[
    str | None, Field(max_length=BUSINESS_FOOTER_MAX_LENGTH), AfterValidator(_optional)
]


class BusinessIn(BaseModel):
    """Replaces every text field (send them all; null or "" clears an optional one)."""

    model_config = ConfigDict(extra="forbid")

    name_km: Name
    name_en: Name
    address_km: Address = None
    address_en: Address = None
    # Checked by core.phones.normalize_phone in the service (INVALID_PHONE).
    phone: Annotated[str | None, Field(max_length=PHONE_INPUT_MAX_LENGTH)] = None
    footer_note_km: Footer = None
    footer_note_en: Footer = None


class BusinessOut(BaseModel):
    name_km: str
    name_en: str
    address_km: str | None
    address_en: str | None
    phone: str | None
    phone_display: str | None
    footer_note_km: str | None
    footer_note_en: str | None
    has_logo: bool
    logo_mime: str | None
    updated_by: UserRef | None
    updated_at: datetime
