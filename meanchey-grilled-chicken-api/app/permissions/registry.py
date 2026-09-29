"""Single source of truth for permissions and the feature access levels built on them.

Adding a feature:
  1. Add its module to MODULES and its permissions to PERMISSIONS below.
  2. Add a FeatureDef to FEATURES so the general manager can set it (Off / View only /
     [Record /] Full access) on the Access tab. Detailed permissions are managed by the
     superadmin only.
  3. Optionally add defaults to DEFAULT_PERMISSIONS. Defaults for a newly added permission are
     also backfilled once to existing active users of those roles (see permissions/sync.py).
  4. Guard the endpoints with `require_permission("<code>")`.
The registry is synced into the `permissions` table on startup, so no migration is needed.
Removing an entry marks the permission inactive; it is never deleted.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

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
    # Optional restriction: for a target role, the only grantor roles that may grant or revoke
    # this permission. Target roles not listed follow the normal hierarchy rules.
    grantable_by: Mapping[Role, tuple[Role, ...]] | None = None


MODULES: list[ModuleDef] = [
    ModuleDef("users", "User management", "គ្រប់គ្រងអ្នកប្រើប្រាស់"),
    ModuleDef("partners", "Partners", "ដៃគូ"),
    ModuleDef("production", "Production", "ផលិតកម្ម"),
]

_MANAGERS = (Role.GENERAL_MANAGER, Role.SUPERVISOR)
_GM_ONLY = (Role.GENERAL_MANAGER,)
_EVERYONE = (Role.GENERAL_MANAGER, Role.SUPERVISOR, Role.STAFF)

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
        # Deactivating people is reserved for the general manager (and the superadmin).
        assignable_to=_GM_ONLY,
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
        # Lets the general manager set feature access levels; supervisors never grant.
        assignable_to=_GM_ONLY,
    ),
]


def _partner_permissions(
    entity: str, name_en: str, name_km: str, plural_en: str
) -> list[PermissionDef]:
    """view / create / update / delete for a partner list (suppliers, customers)."""
    specs = [
        (
            "view",
            f"View {plural_en}",
            f"មើល{name_km}",
            f"See the {name_en} list, contact details and figures.",
            f"មើលបញ្ជី{name_km} ព័ត៌មានទំនាក់ទំនង និងតួលេខសង្ខេប។",
        ),
        (
            "create",
            f"Add {plural_en}",
            f"បន្ថែម{name_km}",
            f"Add new {plural_en} with name, location and phone.",
            f"បញ្ចូល{name_km}ថ្មី ដោយមានឈ្មោះ ទីតាំង និងលេខទូរស័ព្ទ។",
        ),
        (
            "update",
            f"Edit {plural_en}",
            f"កែប្រែ{name_km}",
            f"Change the name, location or phone of {plural_en}.",
            f"កែឈ្មោះ ទីតាំង ឬលេខទូរស័ព្ទរបស់{name_km}។",
        ),
        (
            "delete",
            f"Deactivate {plural_en}",
            f"បិទដំណើរការ{name_km}",
            f"Deactivate {plural_en} you no longer work with, or bring them back.",
            f"បិទ{name_km}ដែលលែងធ្វើការជាមួយ ឬបើកឱ្យដំណើរការឡើងវិញ។",
        ),
    ]
    return [
        PermissionDef(
            code=f"{entity}.{action}",
            module="partners",
            name_en=p_en,
            name_km=p_km,
            description_en=d_en,
            description_km=d_km,
            assignable_to=_EVERYONE,
        )
        for action, p_en, p_km, d_en, d_km in specs
    ]


PERMISSIONS += [
    *_partner_permissions("suppliers", "supplier", "អ្នកផ្គត់ផ្គង់", "suppliers"),
    *_partner_permissions("customers", "customer", "អតិថិជន", "customers"),
]

_PARTNER_CODES = frozenset(p.code for p in PERMISSIONS if p.module == "partners")

PERMISSIONS += [
    PermissionDef(
        code="production.view",
        module="production",
        name_en="View production",
        name_km="មើលផលិតកម្ម",
        description_en="See production batches, their steps and figures.",
        description_km="មើលបាច់ផលិតកម្ម ជំហាននីមួយៗ និងតួលេខសង្ខេប។",
        assignable_to=_EVERYONE,
    ),
    PermissionDef(
        code="production.create",
        module="production",
        name_en="Record production",
        name_km="កត់ត្រាផលិតកម្ម",
        description_en="Start batches, fill in their steps and finish them.",
        description_km="ចាប់ផ្តើមបាច់ថ្មី បំពេញជំហាននីមួយៗ និងបញ្ចប់ជំហាន។",
        assignable_to=_EVERYONE,
    ),
    PermissionDef(
        code="production.update",
        module="production",
        name_en="Reopen production steps",
        name_km="បើកជំហានផលិតកម្មឡើងវិញ",
        description_en="Reopen a finished step so it can be corrected.",
        description_km="បើកជំហានដែលបានបញ្ចប់ឡើងវិញ ដើម្បីកែតម្រូវ។",
        assignable_to=_EVERYONE,
    ),
    PermissionDef(
        code="production.delete",
        module="production",
        name_en="Cancel production batches",
        name_km="លុបចោលបាច់ផលិតកម្ម",
        description_en="Cancel a batch that is still in progress, with a reason.",
        description_km="លុបចោលបាច់ដែលកំពុងដំណើរការ ដោយបញ្ជាក់មូលហេតុ។",
        assignable_to=_EVERYONE,
    ),
]

_PRODUCTION_CODES = frozenset(p.code for p in PERMISSIONS if p.module == "production")

# --- Feature access levels -------------------------------------------------------------------

Level = Literal["off", "view", "record", "full"]
# Every level in display order. A feature uses "off" first, then any of the others in this order
# (most omit "record").
LEVELS: tuple[Level, ...] = ("off", "view", "record", "full")
Menu = Literal["workstation", "settings"]
# Display order of the menus (GET /users/{id}/features groups by it).
MENUS: tuple[Menu, ...] = ("workstation", "settings")


@dataclass(frozen=True)
class FeatureDef:
    """A feature the general manager switches per user: Off / View only / [Record /] Full access.

    Each level is an exact set of permission codes; a user whose permissions (restricted to the
    feature's codes) match no level is shown as "custom". `users.reset_password` and
    `permissions.grant` belong to no feature: they are managed as detailed permissions only.
    """

    code: str
    menu: Menu
    name_en: str
    name_km: str
    description_en: str
    description_km: str
    # Roles the level can be set for.
    applies_to: tuple[Role, ...]
    # Ordered level -> permission codes. Always starts with "off" -> (); order follows LEVELS.
    levels: tuple[tuple[Level, tuple[str, ...]], ...]

    @property
    def level_map(self) -> dict[str, frozenset[str]]:
        return {level: frozenset(codes) for level, codes in self.levels}

    @property
    def codes(self) -> frozenset[str]:
        return frozenset(c for _, codes in self.levels for c in codes)


def _partner_feature(
    entity: str, name_en: str, name_km: str, desc_en: str, desc_km: str
) -> FeatureDef:
    return FeatureDef(
        code=entity,
        menu="workstation",
        name_en=name_en,
        name_km=name_km,
        description_en=desc_en,
        description_km=desc_km,
        applies_to=(Role.SUPERVISOR, Role.STAFF),
        levels=(
            ("off", ()),
            ("view", (f"{entity}.view",)),
            ("full", tuple(f"{entity}.{a}" for a in ("view", "create", "update", "delete"))),
        ),
    )


FEATURES: list[FeatureDef] = [
    _partner_feature(
        "suppliers",
        "Suppliers",
        "អ្នកផ្គត់ផ្គង់",
        "The list of suppliers, with their location and phone.",
        "បញ្ជីអ្នកផ្គត់ផ្គង់ ព្រមទាំងទីតាំង និងលេខទូរស័ព្ទ។",
    ),
    _partner_feature(
        "customers",
        "Customers",
        "អតិថិជន",
        "The list of customers, with their location and phone.",
        "បញ្ជីអតិថិជន ព្រមទាំងទីតាំង និងលេខទូរស័ព្ទ។",
    ),
    FeatureDef(
        code="production",
        menu="workstation",
        name_en="Production",
        name_km="ផលិតកម្ម",
        description_en=(
            "Production batches: raw material, produced and standardize steps. Record lets "
            "someone fill in and finish steps; full access also reopens steps and cancels batches."
        ),
        description_km=(
            "បាច់ផលិតកម្ម៖ វត្ថុធាតុដើម ការកែច្នៃ និងការវេចខ្ចប់។ កម្រិតកត់ត្រាអាចបំពេញ និងបញ្ចប់ជំហាន "
            "ចំណែកសិទ្ធិពេញលេញអាចបើកជំហានឡើងវិញ និងលុបចោលបាច់បានផងដែរ។"
        ),
        applies_to=(Role.SUPERVISOR, Role.STAFF),
        levels=(
            ("off", ()),
            ("view", ("production.view",)),
            ("record", ("production.view", "production.create")),
            (
                "full",
                ("production.view", "production.create", "production.update", "production.delete"),
            ),
        ),
    ),
    FeatureDef(
        code="staff_management",
        menu="settings",
        name_en="Staff management",
        name_km="គ្រប់គ្រងបុគ្គលិក",
        description_en="See staff accounts; with full access, also add and edit them.",
        description_km="មើលគណនីបុគ្គលិក។ បើមានសិទ្ធិពេញលេញ អាចបន្ថែម និងកែប្រែបានផងដែរ។",
        applies_to=(Role.SUPERVISOR,),
        # Supervisors never deactivate users (users.delete is general-manager only).
        levels=(
            ("off", ()),
            ("view", ("users.view",)),
            ("full", ("users.view", "users.create", "users.update")),
        ),
    ),
]

FEATURES_BY_CODE: dict[str, FeatureDef] = {f.code: f for f in FEATURES}


def _feature_defaults(role: Role, levels: dict[str, Level]) -> frozenset[str]:
    codes: set[str] = set()
    for feature in FEATURES:
        if role in feature.applies_to:
            codes |= feature.level_map[levels.get(feature.code, "off")]
    return frozenset(codes)


# Granted automatically when a user of this role is created (limited to what the creator holds).
DEFAULT_PERMISSIONS: dict[Role, frozenset[str]] = {
    Role.GENERAL_MANAGER: frozenset(p.code for p in PERMISSIONS if p.module == "users")
    | _PARTNER_CODES
    | _PRODUCTION_CODES,
    # Every feature at full access.
    Role.SUPERVISOR: _feature_defaults(
        Role.SUPERVISOR,
        {
            "suppliers": "full",
            "customers": "full",
            "production": "full",
            "staff_management": "full",
        },
    ),
    # Every feature off.
    Role.STAFF: _feature_defaults(Role.STAFF, {}),
}


class FeatureRegistryError(RuntimeError):
    """FEATURES references a permission that is unknown or can't be held by one of its roles."""


def validate_features(
    features: list[FeatureDef] | None = None, permissions: list[PermissionDef] | None = None
) -> None:
    """Fail fast when FEATURES doesn't match PERMISSIONS. Runs at import time and at startup."""
    features = FEATURES if features is None else features
    perms = {p.code: p for p in (PERMISSIONS if permissions is None else permissions)}
    for f in features:
        if f.menu not in MENUS:
            raise FeatureRegistryError(f"feature {f.code}: unknown menu {f.menu!r}")
        levels = [level for level, _ in f.levels]
        if not levels or levels[0] != "off" or f.level_map["off"]:
            raise FeatureRegistryError(f"feature {f.code}: first level must be 'off' with no codes")
        if any(level not in LEVELS for level in levels) or levels != sorted(
            set(levels), key=LEVELS.index
        ):
            # Known levels, no duplicates, in LEVELS order ("record" is optional).
            raise FeatureRegistryError(f"feature {f.code}: invalid levels {levels}")
        for code in sorted(f.codes):
            perm = perms.get(code)
            if perm is None:
                raise FeatureRegistryError(f"feature {f.code}: unknown permission {code}")
            missing = [r.value for r in f.applies_to if r not in perm.assignable_to]
            if missing:
                raise FeatureRegistryError(
                    f"feature {f.code}: permission {code} is not assignable to {missing}"
                )
            # Setting a level bypasses per-permission grant rules; don't let it bypass these.
            if perm.grantable_by:
                raise FeatureRegistryError(
                    f"feature {f.code}: permission {code} has grantable_by restrictions"
                )


validate_features()

PERMISSION_ORDER: dict[str, int] = {p.code: i for i, p in enumerate(PERMISSIONS)}
MODULE_ORDER: dict[str, int] = {m.code: i for i, m in enumerate(MODULES)}
MODULES_BY_CODE: dict[str, ModuleDef] = {m.code: m for m in MODULES}
