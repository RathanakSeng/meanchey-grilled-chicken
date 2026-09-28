import re
import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, Field

from app.models.partner import PARTNER_LOCATION_MAX_LENGTH, PARTNER_NAME_MAX_LENGTH
from app.schemas.common import UserRef

_WHITESPACE = re.compile(r"\s+")

# Raw phone input may carry separators; `core.phones.normalize_phone` (in the service) decides
# validity and raises INVALID_PHONE, so this only bounds the request size.
PHONE_INPUT_MAX_LENGTH = 32


def normalize_name(value: str) -> str:
    """Trim and collapse whitespace; must not be empty afterwards."""
    value = _WHITESPACE.sub(" ", value).strip()
    if not value:
        raise ValueError("Name is required")
    if len(value) > PARTNER_NAME_MAX_LENGTH:
        raise ValueError(f"Name must be at most {PARTNER_NAME_MAX_LENGTH} characters")
    return value


def normalize_location(value: str | None) -> str | None:
    """Trim; empty means "no location"."""
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    if len(value) > PARTNER_LOCATION_MAX_LENGTH:
        raise ValueError(f"Location must be at most {PARTNER_LOCATION_MAX_LENGTH} characters")
    return value


PartnerName = Annotated[str, AfterValidator(normalize_name)]
PartnerLocation = Annotated[str | None, AfterValidator(normalize_location)]
PhoneInput = Annotated[str | None, Field(max_length=PHONE_INPUT_MAX_LENGTH)]


class PartnerCreate(BaseModel):
    name: PartnerName
    location: PartnerLocation = None
    phone: PhoneInput = None


class PartnerUpdate(BaseModel):
    """Only fields present in the request body are applied. `null` or "" clears location/phone."""

    name: PartnerName | None = None
    location: PartnerLocation = None
    phone: PhoneInput = None


class PartnerOut(BaseModel):
    id: uuid.UUID
    name: str
    location: str | None
    phone: str | None
    phone_display: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None
    created_by: UserRef | None
    updated_by: UserRef | None


class PartnerPage(BaseModel):
    items: list[PartnerOut]
    total: int
    page: int
    page_size: int


class PartnerStats(BaseModel):
    total_active: int
    # Added during the current calendar month in BUSINESS_TIMEZONE (any status).
    new_this_month: int
    inactive: int


PartnerStatus = Literal["active", "inactive", "all"]
PartnerSort = Literal["name", "-name", "created_at", "-created_at"]
