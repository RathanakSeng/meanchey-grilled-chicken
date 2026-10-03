"""Single source of truth for permissions and the feature access levels built on them.

Adding a feature:
  1. Add its module to MODULES and its permissions to PERMISSIONS below.
  2. Add a FeatureDef to FEATURES so the general manager (for the GM itself: the superadmin)
     can set it (Off / View only / [Record /] Full access) on the Access tab. Detailed
     permissions are managed by the superadmin only.
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
    ModuleDef("production_plan", "Packaging plan", "ផែនការវេចខ្ចប់"),
    ModuleDef("inventory", "Inventory", "ស្តុក"),
    ModuleDef("orders", "Orders", "ការបញ្ជាទិញ"),
    ModuleDef("settings", "Settings", "ការកំណត់"),
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
    PermissionDef(
        code="users.manage_access",
        module="users",
        name_en="Manage staff access",
        name_km="គ្រប់គ្រងសិទ្ធិបុគ្គលិក",
        description_en=(
            "Set the feature access levels of staff within your scope, up to your own access."
        ),
        description_km=("កំណត់កម្រិតសិទ្ធិប្រើប្រាស់មុខងាររបស់បុគ្គលិកក្នុងដែនគ្រប់គ្រងរបស់អ្នក មិនលើសសិទ្ធិរបស់អ្នកឡើយ។"),
        # A supervisor's own grantor permission. Not permissions.grant: its stale rows on old
        # supervisors would silently become effective again.
        assignable_to=(Role.SUPERVISOR,),
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
        name_en="Reopen finished production steps",
        name_km="បើកជំហានផលិតកម្មដែលបានបញ្ចប់ឡើងវិញ",
        description_en=(
            "Reopen a finished step: it and every later step go back to draft (values kept) "
            "and are finished again in order."
        ),
        description_km=(
            "បើកជំហានដែលបានបញ្ចប់ឡើងវិញ៖ ជំហាននោះ និងជំហានបន្ទាប់ៗត្រឡប់ទៅជាព្រាងវិញ (តម្លៃនៅដដែល) "
            "ហើយត្រូវបញ្ចប់ម្តងទៀតតាមលំដាប់។"
        ),
        assignable_to=_EVERYONE,
    ),
    PermissionDef(
        code="production.delete",
        module="production",
        name_en="Cancel production batches",
        name_km="លុបចោលបាច់ផលិតកម្ម",
        description_en=(
            "Cancel a batch that is still in progress, with a reason. General manager only."
        ),
        description_km="លុបចោលបាច់ដែលកំពុងដំណើរការ ដោយបញ្ជាក់មូលហេតុ។ សម្រាប់អ្នកគ្រប់គ្រងទូទៅតែប៉ុណ្ណោះ។",
        # Cancelling is a management decision: never part of a feature level.
        assignable_to=_GM_ONLY,
    ),
]

_PRODUCTION_CODES = frozenset(p.code for p in PERMISSIONS if p.module == "production")

PERMISSIONS += [
    PermissionDef(
        code="production_plan.view",
        module="production_plan",
        name_en="View packaging plans",
        name_km="មើលផែនការវេចខ្ចប់",
        description_en=(
            "See the Production plan tab and every batch's packaging plan, and receive the "
            "production alerts (processing finished, production completed)."
        ),
        description_km=(
            "មើលផ្ទាំងផែនការវេចខ្ចប់ និងផែនការរបស់បាច់នីមួយៗ ព្រមទាំងទទួលការជូនដំណឹងផលិតកម្ម "
            "(ការផលិតរួចរាល់ ផលិតកម្មបានបញ្ចប់)។"
        ),
        assignable_to=_MANAGERS,
    ),
    PermissionDef(
        code="production_plan.manage",
        module="production_plan",
        name_en="Set packaging plans",
        name_km="កំណត់ផែនការវេចខ្ចប់",
        description_en="Fill in, edit and confirm the packaging plan that step 3 waits for.",
        description_km="បំពេញ កែប្រែ និងបញ្ជាក់ផែនការវេចខ្ចប់ ដែលជំហានទី៣ ត្រូវរង់ចាំ។",
        assignable_to=_MANAGERS,
    ),
]

_PLAN_CODES = frozenset(p.code for p in PERMISSIONS if p.module == "production_plan")

PERMISSIONS += [
    PermissionDef(
        code="inventory.view",
        module="inventory",
        name_en="View inventory",
        name_km="មើលស្តុក",
        description_en="See stock and wasted items, and where the current stock came from.",
        description_km="មើលស្តុក ទំនិញខូចខាត និងប្រភពនៃស្តុកបច្ចុប្បន្ន។",
        assignable_to=_EVERYONE,
    ),
    PermissionDef(
        code="inventory.history",
        module="inventory",
        name_en="View inventory history",
        name_km="មើលប្រវត្តិស្តុក",
        description_en=(
            "See every stock movement: the History tab, an item's recent changes and a batch's "
            "stock changes."
        ),
        description_km="មើលការកែប្រែស្តុកទាំងអស់៖ ផ្ទាំងប្រវត្តិ ការកែប្រែថ្មីៗរបស់ទំនិញ និងការកែប្រែស្តុករបស់បាច់។",
        assignable_to=_MANAGERS,
    ),
    # `inventory.adjust` (set stock values) was removed: every item comes from production and
    # changes only through it. The sync marks it inactive; it can return with manual items.
]

PERMISSIONS += [
    PermissionDef(
        code="orders.view",
        module="orders",
        name_en="View orders",
        name_km="មើលការបញ្ជាទិញ",
        description_en="See orders, their boxes, delivery status and returns.",
        description_km="មើលការបញ្ជាទិញ ប្រអប់ ស្ថានភាពដឹកជញ្ជូន និងទំនិញដែលបានប្រគល់មកវិញ។",
        assignable_to=_EVERYONE,
    ),
    PermissionDef(
        code="orders.create",
        module="orders",
        name_en="Record orders",
        name_km="កត់ត្រាការបញ្ជាទិញ",
        description_en=(
            "Create orders, start their delivery, mark them delivered and record what the "
            "customer returned."
        ),
        description_km=("បង្កើតការបញ្ជាទិញ ចាប់ផ្តើមដឹកជញ្ជូន កំណត់ថាបានដឹកដល់ និងកត់ត្រាទំនិញដែលអតិថិជនប្រគល់មកវិញ។"),
        assignable_to=_EVERYONE,
    ),
    PermissionDef(
        code="orders.update",
        module="orders",
        name_en="Edit orders",
        name_km="កែប្រែការបញ្ជាទិញ",
        description_en="Edit orders that haven't left for delivery yet.",
        description_km="កែប្រែការបញ្ជាទិញដែលមិនទាន់ចេញដឹកជញ្ជូន។",
        assignable_to=_MANAGERS,
    ),
    PermissionDef(
        code="orders.cancel",
        module="orders",
        name_en="Cancel orders",
        name_km="លុបចោលការបញ្ជាទិញ",
        description_en="Cancel an order the customer cancelled before delivery, with a reason.",
        description_km="លុបចោលការបញ្ជាទិញដែលអតិថិជនបានលុបចោលមុនពេលដឹកជញ្ជូន ដោយបញ្ជាក់មូលហេតុ។",
        assignable_to=_MANAGERS,
    ),
    PermissionDef(
        code="orders.review_returns",
        module="orders",
        name_en="Review returns",
        name_km="ពិនិត្យទំនិញប្រគល់មកវិញ",
        description_en=(
            "Put returned items back into stock or into wasted, and receive the order alerts "
            "(out for delivery, delivered, returned)."
        ),
        description_km=(
            "ដាក់ទំនិញដែលប្រគល់មកវិញចូលស្តុក ឬទំនិញខូចខាត ព្រមទាំងទទួលការជូនដំណឹងការបញ្ជាទិញ (ចេញដឹក បានដឹកដល់ ប្រគល់មកវិញ)។"
        ),
        assignable_to=_MANAGERS,
    ),
]

_ORDER_CODES = frozenset(p.code for p in PERMISSIONS if p.module == "orders")

PERMISSIONS += [
    PermissionDef(
        code="settings.business_info",
        module="settings",
        name_en="Edit business info",
        name_km="កែប្រែព័ត៌មានអាជីវកម្ម",
        description_en=(
            "Edit the business name, address, phone, logo and footer note printed on delivery "
            "notes."
        ),
        description_km="កែប្រែឈ្មោះ អាសយដ្ឋាន លេខទូរស័ព្ទ ឡូហ្គោ និងកំណត់សម្គាល់ខាងក្រោម ដែលបោះពុម្ពលើប័ណ្ណដឹកជញ្ជូន។",
        # Given to the general manager by the superadmin only (Business info feature).
        assignable_to=_GM_ONLY,
    ),
]

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
    # Only grantors who hold every code of the feature see it and may set it (the superadmin
    # always does). For everyone else it doesn't exist: omitted from GET /users/{id}/features,
    # FEATURE_NOT_FOUND on PUT, and its feature.set audit entries are hidden from them.
    grantor_must_hold: bool = False

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
        applies_to=(Role.GENERAL_MANAGER, Role.SUPERVISOR, Role.STAFF),
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
            "Production batches: intake, processing and standardize steps. Record lets "
            "someone fill in and finish steps; full access also reopens finished steps."
        ),
        description_km=(
            "បាច់ផលិតកម្ម៖ ការនាំចូល ការផលិត និងការវេចខ្ចប់។ កម្រិតកត់ត្រាអាចបំពេញ និងបញ្ចប់ជំហាន "
            "ចំណែកសិទ្ធិពេញលេញអាចបើកជំហានដែលបានបញ្ចប់ឡើងវិញបានផងដែរ។"
        ),
        applies_to=(Role.GENERAL_MANAGER, Role.SUPERVISOR, Role.STAFF),
        levels=(
            ("off", ()),
            ("view", ("production.view",)),
            ("record", ("production.view", "production.create")),
            # production.delete (cancel) is general-manager only, outside the levels.
            ("full", ("production.view", "production.create", "production.update")),
        ),
    ),
    FeatureDef(
        code="production_plan",
        menu="workstation",
        name_en="Production plan",
        name_km="ផែនការវេចខ្ចប់",
        description_en=(
            "Packaging plans between processing and packing. View only: see plans and receive "
            "production alerts; full access: also set and confirm plans."
        ),
        description_km=(
            "ផែនការវេចខ្ចប់ រវាងការផលិត និងការវេចខ្ចប់។ មើលប៉ុណ្ណោះ៖ មើលផែនការ និងទទួលការជូនដំណឹង"
            "ផលិតកម្ម។ សិទ្ធិពេញលេញ៖ អាចកំណត់ និងបញ្ជាក់ផែនការបានផងដែរ។"
        ),
        applies_to=(Role.GENERAL_MANAGER, Role.SUPERVISOR),
        levels=(
            ("off", ()),
            ("view", ("production_plan.view",)),
            ("full", ("production_plan.view", "production_plan.manage")),
        ),
    ),
    FeatureDef(
        code="inventory",
        menu="workstation",
        name_en="Inventory",
        name_km="ស្តុក",
        description_en=(
            "Stock and wasted items, updated automatically by production, and their history."
        ),
        description_km="ស្តុក និងទំនិញខូចខាត ដែលធ្វើបច្ចុប្បន្នភាពដោយស្វ័យប្រវត្តិពីផលិតកម្ម ព្រមទាំងប្រវត្តិ។",
        applies_to=(Role.GENERAL_MANAGER, Role.SUPERVISOR, Role.STAFF),
        levels=(("off", ()), ("view", ("inventory.view",))),
    ),
    FeatureDef(
        code="inventory_history",
        menu="workstation",
        name_en="Inventory history",
        name_km="ប្រវត្តិស្តុក",
        description_en=(
            "Every stock movement, an item's recent changes and a batch's stock changes."
        ),
        description_km="ការកែប្រែស្តុកទាំងអស់ ការកែប្រែថ្មីៗរបស់ទំនិញ និងការកែប្រែស្តុករបស់បាច់។",
        applies_to=(Role.GENERAL_MANAGER, Role.SUPERVISOR),
        levels=(("off", ()), ("view", ("inventory.history",))),
        # Given by the superadmin, or by a GM who has it: invisible to anyone else.
        grantor_must_hold=True,
    ),
    FeatureDef(
        code="orders",
        menu="workstation",
        name_en="Orders",
        name_km="ការបញ្ជាទិញ",
        description_en=(
            "Customer orders packed in boxes, their delivery and returns. Record lets someone "
            "create orders, start delivery and mark them delivered."
        ),
        description_km=(
            "ការបញ្ជាទិញរបស់អតិថិជនដែលវេចក្នុងប្រអប់ ការដឹកជញ្ជូន និងការប្រគល់មកវិញ។ កម្រិតកត់ត្រាអាចបង្កើត"
            "ការបញ្ជាទិញ ចាប់ផ្តើមដឹកជញ្ជូន និងកំណត់ថាបានដឹកដល់។"
        ),
        applies_to=(Role.GENERAL_MANAGER, Role.SUPERVISOR, Role.STAFF),
        levels=(
            ("off", ()),
            ("view", ("orders.view",)),
            ("record", ("orders.view", "orders.create")),
        ),
    ),
    FeatureDef(
        code="order_management",
        menu="workstation",
        name_en="Order management",
        name_km="គ្រប់គ្រងការបញ្ជាទិញ",
        description_en="Edit and cancel orders that haven't left for delivery yet.",
        description_km="កែប្រែ និងលុបចោលការបញ្ជាទិញដែលមិនទាន់ចេញដឹកជញ្ជូន។",
        applies_to=(Role.GENERAL_MANAGER, Role.SUPERVISOR),
        levels=(("off", ()), ("full", ("orders.update", "orders.cancel"))),
    ),
    FeatureDef(
        code="order_returns",
        menu="workstation",
        name_en="Order returns",
        name_km="ទំនិញប្រគល់មកវិញ",
        description_en=(
            "Review returned items (back to stock or wasted) and receive the order alerts."
        ),
        description_km="ពិនិត្យទំនិញដែលប្រគល់មកវិញ (ចូលស្តុក ឬខូចខាត) និងទទួលការជូនដំណឹងការបញ្ជាទិញ។",
        applies_to=(Role.GENERAL_MANAGER, Role.SUPERVISOR),
        levels=(("off", ()), ("full", ("orders.review_returns",))),
    ),
    FeatureDef(
        code="staff_management",
        menu="settings",
        name_en="Staff management",
        name_km="គ្រប់គ្រងបុគ្គលិក",
        description_en=(
            "See staff accounts; record also adds staff, full access also edits their info."
        ),
        description_km=(
            "មើលគណនីបុគ្គលិក។ កម្រិតកត់ត្រាអាចបន្ថែមបុគ្គលិក ចំណែកសិទ្ធិពេញលេញអាចកែប្រែព័ត៌មានរបស់ពួកគេបានផងដែរ។"
        ),
        applies_to=(Role.GENERAL_MANAGER, Role.SUPERVISOR),
        # Supervisors never deactivate users (users.delete is general-manager only).
        levels=(
            ("off", ()),
            ("view", ("users.view",)),
            ("record", ("users.view", "users.create")),
            ("full", ("users.view", "users.create", "users.update")),
        ),
    ),
    FeatureDef(
        code="staff_access",
        menu="settings",
        name_en="Staff access",
        name_km="សិទ្ធិបុគ្គលិក",
        description_en="Can set what staff can use, up to their own access.",
        description_km="អាចកំណត់អ្វីដែលបុគ្គលិកអាចប្រើបាន មិនលើសសិទ្ធិរបស់ខ្លួនឡើយ។",
        applies_to=(Role.SUPERVISOR,),
        levels=(("off", ()), ("full", ("users.manage_access",))),
    ),
    FeatureDef(
        code="business_info",
        menu="settings",
        name_en="Business info",
        name_km="ព័ត៌មានអាជីវកម្ម",
        description_en=(
            "Edit the business name, address, phone, logo and footer note on delivery notes."
        ),
        description_km="កែប្រែឈ្មោះ អាសយដ្ឋាន លេខទូរស័ព្ទ ឡូហ្គោ និងកំណត់សម្គាល់ខាងក្រោម លើប័ណ្ណដឹកជញ្ជូន។",
        # Only the superadmin manages the GM, so only it can turn this on.
        applies_to=(Role.GENERAL_MANAGER,),
        levels=(("off", ()), ("full", ("settings.business_info",))),
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
    # users.manage_access is supervisor-only: the GM sets access with permissions.grant.
    Role.GENERAL_MANAGER: frozenset(
        p.code
        for p in PERMISSIONS
        if p.module == "users" and Role.GENERAL_MANAGER in p.assignable_to
    )
    | _PARTNER_CODES
    | _PRODUCTION_CODES
    | _PLAN_CODES
    # Inventory View; Inventory history is Off until the superadmin allows it.
    | {"inventory.view"}
    # Orders Record, management Full, returns Full.
    | _ORDER_CODES,
    # Workstation features at full access, except the production plan (off: the GM decides who
    # plans). Staff: view them and set their access; adding or editing staff is the GM's call.
    Role.SUPERVISOR: _feature_defaults(
        Role.SUPERVISOR,
        {
            "suppliers": "full",
            "customers": "full",
            "production": "full",
            "production_plan": "off",
            "inventory": "view",
            "inventory_history": "off",
            # Orders Record; editing, cancelling and reviewing returns are the GM's to allow.
            "orders": "record",
            "order_management": "off",
            "order_returns": "off",
            "staff_management": "view",
            "staff_access": "full",
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
