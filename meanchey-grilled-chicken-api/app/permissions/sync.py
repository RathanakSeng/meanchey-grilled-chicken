import logging
from collections.abc import Mapping

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Permission, Role, User, UserPermission
from app.permissions.registry import DEFAULT_PERMISSIONS, PERMISSION_ORDER, PERMISSIONS
from app.services.audit_service import record

log = logging.getLogger(__name__)


def _grantable_by_json(value: Mapping[Role, tuple[Role, ...]] | None) -> dict | None:
    if not value:
        return None
    return {target.value: [g.value for g in grantors] for target, grantors in value.items()}


async def sync_registry(session: AsyncSession) -> list[str]:
    """Upsert registry entries into `permissions`; deactivate ones no longer in the registry.

    Returns the codes inserted by this run (new permissions). Does not commit; the caller owns
    the transaction.
    """
    existing = {p.code: p for p in (await session.scalars(select(Permission))).all()}
    registry_codes: set[str] = set()
    inserted: list[str] = []

    for d in PERMISSIONS:
        registry_codes.add(d.code)
        values = {
            "module": d.module,
            "name_en": d.name_en,
            "name_km": d.name_km,
            "description_en": d.description_en,
            "description_km": d.description_km,
            "assignable_to": [r.value for r in d.assignable_to],
            "grantable_by": _grantable_by_json(d.grantable_by),
            "is_active": True,
        }
        row = existing.get(d.code)
        if row is None:
            session.add(Permission(code=d.code, **values))
            inserted.append(d.code)
            log.info("permission registered: %s", d.code)
        else:
            for key, value in values.items():
                setattr(row, key, value)

    for code, row in existing.items():
        if code not in registry_codes and row.is_active:
            row.is_active = False
            log.warning("permission removed from registry, marked inactive: %s", code)

    await session.flush()
    return inserted


async def backfill_defaults(session: AsyncSession, codes: list[str]) -> int:
    """Grant newly registered permissions to existing active users whose role has them as a default.

    Defaults are otherwise only applied when a user is created, so without this a new feature
    would be invisible to every existing manager until someone granted it by hand. Only called
    with the codes `sync_registry` just inserted, so it runs once per permission. Grants are
    recorded as made by the system (`granted_by` NULL). Does not commit.
    """
    if not codes:
        return 0
    perms = {
        p.code: p
        for p in await session.scalars(select(Permission).where(Permission.code.in_(codes)))
    }
    granted = 0
    for role, defaults in DEFAULT_PERMISSIONS.items():
        role_codes = sorted(
            (
                c
                for c in defaults
                if c in perms and perms[c].is_active and role.value in perms[c].assignable_to
            ),
            key=lambda c: PERMISSION_ORDER.get(c, 999),
        )
        if not role_codes:
            continue
        user_ids = list(
            await session.scalars(select(User.id).where(User.role == role, User.is_active))
        )
        for user_id in user_ids:
            for code in role_codes:
                inserted = await session.scalar(
                    pg_insert(UserPermission)
                    .values(user_id=user_id, permission_code=code, granted_by=None)
                    .on_conflict_do_nothing()
                    .returning(UserPermission.user_id)
                )
                if inserted is None:
                    continue
                record(
                    session,
                    "permission.grant",
                    target_user_id=user_id,
                    details={"permission": code, "source": "default_backfill"},
                )
                granted += 1
    if granted:
        log.info("backfilled %d default permission grant(s) for %s", granted, ", ".join(codes))
    await session.flush()
    return granted
