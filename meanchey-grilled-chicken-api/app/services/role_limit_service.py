"""Role limits: how many active general managers, supervisors and staff there may be.

- `ensure_slot(session, role)` runs inside the caller's transaction before a user of `role` becomes
  active (create, reactivate, change role). It locks the role's `role_limits` row
  (`SELECT … FOR UPDATE`) and counts active users; at or above the limit → `409 ROLE_LIMIT_REACHED`
  with `{role, limit, active}`. The lock serializes concurrent requests for the same role, so
  exactly one can take the last slot. Only active users count; the superadmin is never counted.
- Lowering a limit below the current count is allowed: nobody is deactivated, the role is simply
  full (`over_limit`) until enough users leave it.
- Limits are set by the superadmin only (route guard); changes are audited
  (`settings.role_limit_update`), which the audit log hides from general managers like everything
  the superadmin does.
"""

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, ErrorCode
from app.models import Role, RoleLimit, User, utcnow
from app.models.role_limit import LIMITED_ROLES, MAX_ROLE_LIMIT
from app.permissions.hierarchy import MANAGEABLE_ROLES
from app.schemas.common import UserRef
from app.schemas.role_limit import RoleCapacityOut, RoleLimitOut
from app.services.audit_service import record


async def _active_count(session: AsyncSession, role: Role) -> int:
    return (
        await session.scalar(select(func.count(User.id)).where(User.role == role, User.is_active))
        or 0
    )


async def _active_counts(session: AsyncSession) -> dict[str, int]:
    rows = await session.execute(
        select(User.role, func.count(User.id)).where(User.is_active).group_by(User.role)
    )
    return {role.value: n for role, n in rows}


async def ensure_slot(session: AsyncSession, role: Role) -> None:
    """Raise ROLE_LIMIT_REACHED when `role` has no free slot. Locks the limit row until commit."""
    if role not in LIMITED_ROLES:
        return
    limit = await session.scalar(
        select(RoleLimit.max_active).where(RoleLimit.role == role.value).with_for_update()
    )
    if limit is None:
        return  # unlimited (or no row yet: bootstrap seeds one)
    active = await _active_count(session, role)
    if active >= limit:
        raise AppError(
            409,
            ErrorCode.ROLE_LIMIT_REACHED,
            "The limit of active users for this role is reached",
            {"role": role.value, "limit": limit, "active": active},
        )


async def _rows(session: AsyncSession) -> dict[str, RoleLimit]:
    return {r.role: r for r in await session.scalars(select(RoleLimit))}


async def list_limits(session: AsyncSession) -> list[RoleLimitOut]:
    rows = await _rows(session)
    counts = await _active_counts(session)
    editors = {r.updated_by for r in rows.values() if r.updated_by}
    users = (
        {u.id: u for u in await session.scalars(select(User).where(User.id.in_(editors)))}
        if editors
        else {}
    )
    out = []
    for role in LIMITED_ROLES:
        row = rows.get(role.value)
        limit = row.max_active if row else None
        active = counts.get(role.value, 0)
        editor = users.get(row.updated_by) if row and row.updated_by else None
        out.append(
            RoleLimitOut(
                role=role,
                max_active=limit,
                active=active,
                over_limit=limit is not None and active > limit,
                updated_by=UserRef.model_validate(editor) if editor else None,
                updated_at=row.updated_at if row else None,
            )
        )
    return out


def _invalid(msg: str) -> AppError:
    return AppError(
        422,
        ErrorCode.VALIDATION_ERROR,
        msg,
        {"fields": [{"loc": ["body", "max_active"], "type": "value_error", "msg": msg}]},
    )


async def set_limit(
    session: AsyncSession, actor: User, role: Role, max_active: int | None
) -> list[RoleLimitOut]:
    if role not in LIMITED_ROLES:
        # Also the superadmin: always exactly one, never configurable.
        raise _invalid("This role has no limit")
    if max_active is None and role == Role.GENERAL_MANAGER:
        raise _invalid("General managers can't be unlimited")
    if max_active is not None and not 1 <= max_active <= MAX_ROLE_LIMIT:
        raise _invalid(f"Must be between 1 and {MAX_ROLE_LIMIT}")
    row = await session.scalar(
        select(RoleLimit).where(RoleLimit.role == role.value).with_for_update()
    )
    previous = row.max_active if row else None
    if row is not None and previous == max_active:
        return await list_limits(session)  # same value again: nothing written
    if row is None:
        row = RoleLimit(role=role.value)
        session.add(row)
    row.max_active = max_active
    row.updated_by = actor.id
    row.updated_at = utcnow()
    details: dict[str, Any] = {"role": role.value, "from": previous, "to": max_active}
    record(session, "settings.role_limit_update", actor_id=actor.id, details=details)
    await session.commit()
    return await list_limits(session)


async def capacity(session: AsyncSession, viewer: User) -> list[RoleCapacityOut]:
    """Active count and limit for the roles `viewer` manages (never their own or higher)."""
    rows = await _rows(session)
    counts = await _active_counts(session)
    managed = MANAGEABLE_ROLES[viewer.role]
    out = []
    for role in LIMITED_ROLES:
        if role not in managed:
            continue
        row = rows.get(role.value)
        limit = row.max_active if row else None
        active = counts.get(role.value, 0)
        out.append(
            RoleCapacityOut(
                role=role, active=active, limit=limit, full=limit is not None and active >= limit
            )
        )
    return out
