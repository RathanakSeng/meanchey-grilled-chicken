"""Single source of truth for feature permissions.

Adding a feature:
  1. Add its module to MODULES and its permissions to PERMISSIONS below.
  2. Optionally add defaults to DEFAULT_PERMISSIONS.
  3. Guard the endpoints with `require_permission("<code>")`.
The registry is synced into the `permissions` table on startup, so no migration is needed.
Removing an entry marks the permission inactive; it is never deleted.
"""

from dataclasses import dataclass

from app.models.enums import Role


@dataclass(frozen=True)
class ModuleDef:
    code: str
    name_en: str
    name_km: str


@dataclass(frozen=True)
class PermissionDef:
    code: str
    module: str
    name_en: str
    name_km: str
    description_en: str
    description_km: str
    # Roles that may ever receive this permission. Superadmin implicitly holds everything.
    assignable_to: tuple[Role, ...]


MODULES: list[ModuleDef] = [
    ModuleDef("users", "User management", "គ្រប់គ្រងអ្នកប្រើប្រាស់"),
]

_MANAGERS = (Role.GENERAL_MANAGER, Role.SUPERVISOR)

PERMISSIONS: list[PermissionDef] = [
    PermissionDef(
        code="users.view",
        module="users",
        name_en="View users",
        name_km="មើលអ្នកប្រើប្រាស់",
        description_en="View users within your scope.",
        description_km="មើលអ្នកប្រើប្រាស់ក្នុងដែនគ្រប់គ្រងរបស់អ្នក។",
        assignable_to=_MANAGERS,
    ),
    PermissionDef(
        code="users.create",
        module="users",
        name_en="Create users",
        name_km="បង្កើតអ្នកប្រើប្រាស់",
        description_en="Create users within your scope.",
        description_km="បង្កើតអ្នកប្រើប្រាស់ក្នុងដែនគ្រប់គ្រងរបស់អ្នក។",
        assignable_to=_MANAGERS,
    ),
    PermissionDef(
        code="users.update",
        module="users",
        name_en="Edit users",
        name_km="កែប្រែអ្នកប្រើប្រាស់",
        description_en="Edit users within your scope.",
        description_km="កែប្រែព័ត៌មានអ្នកប្រើប្រាស់ក្នុងដែនគ្រប់គ្រងរបស់អ្នក។",
        assignable_to=_MANAGERS,
    ),
    PermissionDef(
        code="users.delete",
        module="users",
        name_en="Deactivate users",
        name_km="បិទ/បើកគណនីអ្នកប្រើប្រាស់",
        description_en="Deactivate or reactivate users within your scope.",
        description_km="បិទ ឬបើកគណនីអ្នកប្រើប្រាស់ក្នុងដែនគ្រប់គ្រងរបស់អ្នកឡើងវិញ។",
        assignable_to=_MANAGERS,
    ),
    PermissionDef(
        code="users.reset_password",
        module="users",
        name_en="Reset passwords",
        name_km="កំណត់ពាក្យសម្ងាត់ឡើងវិញ",
        description_en=(
            "Reset the password of users within your scope, or your own, to the Telegram username."
        ),
        description_km=("កំណត់ពាក្យសម្ងាត់របស់អ្នកប្រើប្រាស់ក្នុងដែនគ្រប់គ្រង ឬរបស់ខ្លួនឯង ទៅជាឈ្មោះ Telegram វិញ។"),
        # Only the general manager (and the superadmin, implicitly) may reset passwords.
        assignable_to=(Role.GENERAL_MANAGER,),
    ),
    PermissionDef(
        code="permissions.grant",
        module="users",
        name_en="Grant permissions",
        name_km="ផ្តល់សិទ្ធិ",
        description_en="Grant or revoke permissions you hold to users within your scope.",
        description_km="ផ្តល់ ឬដកសិទ្ធិដែលអ្នកមាន ទៅអ្នកប្រើប្រាស់ក្នុងដែនគ្រប់គ្រងរបស់អ្នក។",
        assignable_to=_MANAGERS,
    ),
]

# Granted automatically when a user of this role is created (limited to what the creator holds).
DEFAULT_PERMISSIONS: dict[Role, frozenset[str]] = {
    Role.GENERAL_MANAGER: frozenset(p.code for p in PERMISSIONS if p.module == "users"),
    Role.SUPERVISOR: frozenset({"users.view", "users.create", "users.update"}),
    Role.STAFF: frozenset(),
}

PERMISSION_ORDER: dict[str, int] = {p.code: i for i, p in enumerate(PERMISSIONS)}
MODULE_ORDER: dict[str, int] = {m.code: i for i, m in enumerate(MODULES)}
MODULES_BY_CODE: dict[str, ModuleDef] = {m.code: m for m in MODULES}
