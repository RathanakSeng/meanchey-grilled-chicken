from enum import StrEnum

from sqlalchemy import Enum


class Role(StrEnum):
    SUPERADMIN = "superadmin"
    GENERAL_MANAGER = "general_manager"
    SUPERVISOR = "supervisor"
    STAFF = "staff"


class Language(StrEnum):
    KM = "km"
    EN = "en"


def _values(enum_cls: type[StrEnum]) -> list[str]:
    return [m.value for m in enum_cls]


role_type = Enum(Role, name="user_role", values_callable=_values)
language_type = Enum(
    Language, name="user_language", native_enum=False, length=8, values_callable=_values
)
