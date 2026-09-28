import re
import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

from app.models import Language, Role
from app.models.user import POSITION_MAX_LENGTH

PHONE_PATTERN = r"^[0-9+()\-\s]{6,32}$"

_WHITESPACE = re.compile(r"\s+")


def normalize_position(value: str | None) -> str | None:
    """Trim and collapse whitespace; keep case and script. Empty means "no position"."""
    if value is None:
        return None
    value = _WHITESPACE.sub(" ", value).strip()
    if not value:
        return None
    if len(value) > POSITION_MAX_LENGTH:
        raise ValueError(f"Position must be at most {POSITION_MAX_LENGTH} characters")
    return value


# Free-text job title (e.g. "Grill cook", "អ្នកដឹកជញ្ជូន"). A label only, never used for access.
PositionText = Annotated[str | None, AfterValidator(normalize_position)]


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    role: Role
    position: str | None
    full_name: str
    phone: str | None
    telegram_username: str | None
    telegram_linked: bool
    language: Language
    is_active: bool
    must_change_password: bool
    created_by: uuid.UUID | None
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None
    locked_until: datetime | None


class UserCreate(BaseModel):
    role: Role
    position: PositionText = None
    full_name: str = Field(min_length=1, max_length=120)
    telegram_username: str = Field(min_length=1, max_length=40)
    phone: str | None = Field(default=None, pattern=PHONE_PATTERN)
    language: Language = Language.KM


class UserUpdate(BaseModel):
    """Only fields present in the request body are applied."""

    full_name: str | None = Field(default=None, min_length=1, max_length=120)
    telegram_username: str | None = Field(default=None, min_length=1, max_length=40)
    phone: str | None = Field(default=None, pattern=PHONE_PATTERN)
    position: PositionText = None
    language: Language | None = None


class ProfileUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=1, max_length=120)
    phone: str | None = Field(default=None, pattern=PHONE_PATTERN)
    language: Language | None = None


UserStatus = Literal["active", "inactive", "all"]


class UserPage(BaseModel):
    items: list[UserOut]
    total: int
    page: int
    page_size: int
