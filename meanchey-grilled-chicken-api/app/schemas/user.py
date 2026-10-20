import re
import uuid
from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import AfterValidator, AliasChoices, BaseModel, ConfigDict, Field

from app.models import Language, Role
from app.models.user import POSITION_MAX_LENGTH
from app.schemas.attendance import UserWorkplace
from app.schemas.common import UserRef

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
    # Who created the account ("System" for hidden accounts, see services/redaction.py).
    created_by: UserRef | None = Field(validation_alias=AliasChoices("creator", "created_by"))
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None
    locked_until: datetime | None
    # Attendance workplace (staff and supervisors).
    workplace: UserWorkplace | None = None
    # Attendance tracking: the first tracked day (staff and supervisors), whether the user is
    # tracked (a supervisor can be switched off) and since when they aren't.
    attendance_start_date: date | None = None
    attendance_tracked: bool = True
    attendance_untracked_since: date | None = None


class UserCreate(BaseModel):
    role: Role
    position: PositionText = None
    full_name: str = Field(min_length=1, max_length=120)
    telegram_username: str = Field(min_length=1, max_length=40)
    phone: str | None = Field(default=None, pattern=PHONE_PATTERN)
    language: Language = Language.KM
    # Staff and supervisors: an active attendance workplace (default: the default workplace).
    workplace_id: uuid.UUID | None = None
    # Staff and supervisors: the first day attendance is tracked (default today, not in the past).
    attendance_start_date: date | None = None


class UserUpdate(BaseModel):
    """Only fields present in the request body are applied."""

    full_name: str | None = Field(default=None, min_length=1, max_length=120)
    telegram_username: str | None = Field(default=None, min_length=1, max_length=40)
    phone: str | None = Field(default=None, pattern=PHONE_PATTERN)
    position: PositionText = None
    language: Language | None = None
    # Staff and supervisors: move to another active attendance workplace.
    workplace_id: uuid.UUID | None = None
    # Only while the current start date is still in the future (else 409 ATTENDANCE_START_LOCKED).
    attendance_start_date: date | None = None
    # Supervisors only (staff are always tracked): switch their attendance off / on from today.
    attendance_tracked: bool | None = None


class RoleChange(BaseModel):
    """Promote / demote. `position` is required when the new role is staff, forbidden otherwise.
    `workplace_id` (staff, supervisor): the attendance workplace; default: keep it, else the
    default workplace."""

    role: Role
    position: PositionText = None
    workplace_id: uuid.UUID | None = None
    # Moving into staff / supervisor: the first tracked day (default today; kept when the user
    # is already staff or supervisor and none is given).
    attendance_start_date: date | None = None


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
