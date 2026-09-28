import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict, SerializerFunctionWrapHandler, model_serializer

from app.models import Role
from app.services.redaction import SYSTEM_NAME, hides


class UserRef(BaseModel):
    """Compact reference to a user. Use it for EVERY user reference in a response.

    For viewers other than the superadmin, a reference to the superadmin serializes as
    `{id: null, full_name: "System", role: null, telegram_username: null, is_system: true}`
    (see services/redaction.py).
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID | None
    full_name: str
    role: Role | None = None
    telegram_username: str | None = None
    # True for actions made by the system (e.g. automatic grants) or hidden accounts.
    is_system: bool = False

    @model_serializer(mode="wrap")
    def _redact(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        if hides(self.role):
            return system_ref()
        return handler(self)


def system_ref() -> dict[str, Any]:
    return {
        "id": None,
        "full_name": SYSTEM_NAME,
        "role": None,
        "telegram_username": None,
        "is_system": True,
    }
