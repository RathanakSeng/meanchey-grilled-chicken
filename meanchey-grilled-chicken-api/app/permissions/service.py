import uuid
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import ColumnElement, any_, delete, literal, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, ErrorCode
from app.models import Permission, Role, User, UserPermission
from app.permissions.hierarchy import can_manage, ensure_can_manage
from app.permissions.registry import (
    DEFAULT_PERMISSIONS,
    MODULE_ORDER,
    MODULES_BY_CODE,
    PERMISSION_ORDER,
)
from app.services.audit_service import record

GRANT_PERMISSION = "permissions.grant"


def _assignable_to(role: Role) -> ColumnElement[bool]:
    return literal(role.value) == any_(Permission.assignable_to)


async def effective_permissions(session: AsyncSession, user: User) -> set[str]:
    """Active permission codes the user holds. The superadmin implicitly holds all of them."""
    if user.role == Role.SUPERADMIN:
        return set(await session.scalars(select(Permission.code).where(Permission.is_active)))
    stmt = (
        select(UserPermission.permission_code)
        .join(Permission, Permission.code == UserPermission.permission_code)
        .where(
            UserPermission.user_id == user.id,
            Permission.is_active,
            _assignable_to(user.role),
        )
    )
    return set(await session.scalars(stmt))


def _sort_key(p: Permission) -> tuple[int, int, str]:
    return (MODULE_ORDER.get(p.module, 999), PERMISSION_ORDER.get(p.code, 999), p.code)


@dataclass
class PermissionState:
    permission: Permission
    granted: bool = False
    granted_by: uuid.UUID | None = None
    granted_at: datetime | None = None
    can_edit: bool = False


@dataclass
class ModuleGroup:
    module: str
    name_en: str
    name_km: str
    permissions: list = field(default_factory=list)


def group_by_module(items: list, get_perm) -> list[ModuleGroup]:
    groups: dict[str, ModuleGroup] = {}
    for item in items:
        perm: Permission = get_perm(item)
        mod = MODULES_BY_CODE.get(perm.module)
        group = groups.setdefault(
            perm.module,
            ModuleGroup(
                module=perm.module,
                name_en=mod.name_en if mod else perm.module,
                name_km=mod.name_km if mod else perm.module,
            ),
        )
        group.permissions.append(item)
    return list(groups.values())


async def catalog(session: AsyncSession) -> list[ModuleGroup]:
    perms = list(await session.scalars(select(Permission).where(Permission.is_active)))
    perms.sort(key=_sort_key)
    return group_by_module(perms, lambda p: p)


async def user_permission_matrix(
    session: AsyncSession, actor: User, target: User
) -> list[ModuleGroup]:
    """Every active permission assignable to the target's role, with grant state and editability."""
    perms = list(
        await session.scalars(
            select(Permission).where(Permission.is_active, _assignable_to(target.role))
        )
    )
    perms.sort(key=_sort_key)
    grants = {
        g.permission_code: g
        for g in await session.scalars(
            select(UserPermission).where(UserPermission.user_id == target.id)
        )
    }
    actor_perms = await effective_permissions(session, actor)
    may_edit = target.is_active and can_manage(actor, target) and GRANT_PERMISSION in actor_perms

    states = []
    for p in perms:
        g = grants.get(p.code)
        states.append(
            PermissionState(
                permission=p,
                granted=g is not None,
                granted_by=g.granted_by if g else None,
                granted_at=g.granted_at if g else None,
                can_edit=may_edit and p.code in actor_perms,
            )
        )
    return group_by_module(states, lambda s: s.permission)


async def grant_defaults(session: AsyncSession, actor: User, target: User) -> list[str]:
    """Grant the role's default permissions, limited to those the creator holds."""
    defaults = DEFAULT_PERMISSIONS.get(target.role, frozenset())
    if not defaults:
        return []
    assignable = set(
        await session.scalars(
            select(Permission.code).where(Permission.is_active, _assignable_to(target.role))
        )
    )
    actor_perms = await effective_permissions(session, actor)
    codes = sorted(defaults & assignable & actor_perms, key=lambda c: PERMISSION_ORDER.get(c, 999))
    for code in codes:
        session.add(UserPermission(user_id=target.id, permission_code=code, granted_by=actor.id))
    await session.flush()
    return codes


async def _check_grant(session: AsyncSession, actor: User, target: User, code: str) -> Permission:
    ensure_can_manage(actor, target)
    perm = await session.get(Permission, code)
    if perm is None or not perm.is_active:
        raise AppError(404, ErrorCode.PERMISSION_NOT_FOUND, f"Unknown permission {code}")
    if code not in await effective_permissions(session, actor):
        raise AppError(
            403, ErrorCode.PERMISSION_NOT_HELD, "You can only grant or revoke permissions you hold"
        )
    return perm


async def grant(session: AsyncSession, actor: User, target: User, code: str) -> None:
    perm = await _check_grant(session, actor, target, code)
    if not target.is_active:
        raise AppError(409, ErrorCode.USER_INACTIVE, "User is deactivated")
    if target.role.value not in perm.assignable_to:
        raise AppError(
            422,
            ErrorCode.PERMISSION_NOT_ASSIGNABLE,
            f"Permission {code} cannot be granted to role {target.role}",
        )
    inserted = await session.scalar(
        pg_insert(UserPermission)
        .values(user_id=target.id, permission_code=code, granted_by=actor.id)
        .on_conflict_do_nothing()
        .returning(UserPermission.user_id)
    )
    if inserted is not None:
        record(
            session,
            "permission.grant",
            actor_id=actor.id,
            target_user_id=target.id,
            details={"permission": code},
        )
    await session.commit()


async def revoke(session: AsyncSession, actor: User, target: User, code: str) -> None:
    await _check_grant(session, actor, target, code)
    deleted = await session.scalar(
        delete(UserPermission)
        .where(UserPermission.user_id == target.id, UserPermission.permission_code == code)
        .returning(UserPermission.user_id)
    )
    if deleted is not None:
        # No cascade: grants this user made of the same permission stay; we surface them.
        downstream = (
            await session.execute(
                select(User.id, User.full_name, User.telegram_username)
                .join(UserPermission, UserPermission.user_id == User.id)
                .where(
                    UserPermission.granted_by == target.id,
                    UserPermission.permission_code == code,
                    User.is_active,
                )
            )
        ).all()
        record(
            session,
            "permission.revoke",
            actor_id=actor.id,
            target_user_id=target.id,
            details={
                "permission": code,
                "downstream_grants": [
                    {"user_id": str(uid), "full_name": name, "telegram_username": uname}
                    for uid, name, uname in downstream
                ],
            },
        )
    await session.commit()
