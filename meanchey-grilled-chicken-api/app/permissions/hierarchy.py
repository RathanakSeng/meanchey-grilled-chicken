"""Role hierarchy: decides WHO a user may manage. Permissions decide WHAT they may do."""

from app.core.errors import AppError, ErrorCode
from app.models import Role, User

ROLE_LEVEL: dict[Role, int] = {
    Role.SUPERADMIN: 0,
    Role.GENERAL_MANAGER: 1,
    Role.SUPERVISOR: 2,
    Role.STAFF: 3,
}

MANAGEABLE_ROLES: dict[Role, frozenset[Role]] = {
    Role.SUPERADMIN: frozenset({Role.GENERAL_MANAGER, Role.SUPERVISOR, Role.STAFF}),
    Role.GENERAL_MANAGER: frozenset({Role.SUPERVISOR, Role.STAFF}),
    Role.SUPERVISOR: frozenset({Role.STAFF}),
    Role.STAFF: frozenset(),
}


def manageable_roles(role: Role) -> list[Role]:
    return sorted(MANAGEABLE_ROLES[role], key=ROLE_LEVEL.__getitem__)


def can_manage(actor: User, target: User) -> bool:
    """Users never manage themselves through the admin endpoints; they use /me."""
    if actor.id == target.id:
        return False
    return target.role in MANAGEABLE_ROLES[actor.role]


def ensure_can_manage(actor: User, target: User) -> None:
    if not can_manage(actor, target):
        raise AppError(403, ErrorCode.FORBIDDEN_SCOPE, "Target user is outside your scope")


def ensure_can_manage_role(actor: User, role: Role) -> None:
    if role not in MANAGEABLE_ROLES[actor.role]:
        raise AppError(403, ErrorCode.FORBIDDEN_SCOPE, f"You cannot manage users with role {role}")
