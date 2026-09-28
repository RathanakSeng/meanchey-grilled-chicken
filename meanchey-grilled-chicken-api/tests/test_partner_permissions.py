"""Default backfill for new permissions, and the (currently unused) grantable_by mechanism."""

import pytest
from sqlalchemy import delete, select, update

from app.bootstrap import bootstrap
from app.core.errors import AppError
from app.models import AuditLog, Permission, Role, UserPermission
from app.permissions import registry, service
from tests.conftest import auth

USER_PERMS = ["users.view", "users.create", "users.update"]
PARTNERS = {
    f"{entity}.{action}"
    for entity in ("suppliers", "customers")
    for action in ("view", "create", "update", "delete")
}


def _grant(client, actor, target, code):
    return client.put(f"/users/{target.id}/permissions/{code}", headers=auth(actor))


def _revoke(client, actor, target, code):
    return client.delete(f"/users/{target.id}/permissions/{code}", headers=auth(actor))


async def _held(session, user) -> set[str]:
    return set(
        await session.scalars(
            select(UserPermission.permission_code).where(UserPermission.user_id == user.id)
        )
    )


async def _matrix(client, actor, target) -> dict[str, dict]:
    r = await client.get(f"/users/{target.id}/permissions", headers=auth(actor))
    assert r.status_code == 200, r.text
    return {p["code"]: p for m in r.json()["modules"] for p in m["permissions"]}


# --- Backfill ----------------------------------------------------------------------------------


async def _simulate_pre_partner_deploy(session) -> None:
    """Make the partner permissions look brand new, as before this feature was deployed."""
    await session.execute(
        delete(UserPermission).where(UserPermission.permission_code.in_(PARTNERS))
    )
    await session.execute(delete(Permission).where(Permission.code.in_(PARTNERS)))
    await session.execute(delete(AuditLog))
    await session.commit()


async def test_backfill_grants_new_defaults_to_existing_managers(session, make_user) -> None:
    gm = await make_user(Role.GENERAL_MANAGER, perms=USER_PERMS)
    sup1 = await make_user(Role.SUPERVISOR, perms=USER_PERMS)
    sup2 = await make_user(Role.SUPERVISOR, perms=[])
    inactive_sup = await make_user(Role.SUPERVISOR, perms=USER_PERMS, is_active=False)
    staff = await make_user(Role.STAFF)
    await _simulate_pre_partner_deploy(session)

    await bootstrap(session)

    for user in (gm, sup1, sup2):
        assert await _held(session, user) >= PARTNERS
    assert await _held(session, inactive_sup) == set(USER_PERMS)
    assert await _held(session, staff) == set()
    # Existing grants are untouched.
    assert await _held(session, sup2) == PARTNERS

    logs = list(
        await session.scalars(select(AuditLog).where(AuditLog.action == "permission.grant"))
    )
    assert len(logs) == 3 * len(PARTNERS)
    assert all(log.details["source"] == "default_backfill" for log in logs)
    assert all(log.actor_id is None for log in logs)
    assert {log.target_user_id for log in logs} == {gm.id, sup1.id, sup2.id}
    grants = list(
        await session.scalars(
            select(UserPermission).where(UserPermission.permission_code.in_(PARTNERS))
        )
    )
    assert all(g.granted_by is None for g in grants)


async def test_backfill_is_idempotent(session, make_user) -> None:
    await make_user(Role.GENERAL_MANAGER, perms=USER_PERMS)
    await _simulate_pre_partner_deploy(session)
    await bootstrap(session)
    count = len(list(await session.scalars(select(AuditLog))))

    await bootstrap(session)

    assert len(list(await session.scalars(select(AuditLog)))) == count


async def test_backfill_skips_revoked_permission_on_later_starts(
    client, session, superadmin, make_user
) -> None:
    """Only newly inserted permissions are backfilled: a deliberate revoke sticks."""
    sup = await make_user(Role.SUPERVISOR)
    assert (await _revoke(client, superadmin, sup, "suppliers.delete")).status_code == 204
    await bootstrap(session)
    assert "suppliers.delete" not in await _held(session, sup)


# --- grantable_by (mechanism kept for future use; no permission uses it today) --------------


async def test_partner_permissions_have_no_grantable_by(session) -> None:
    rows = await session.scalars(select(Permission).where(Permission.code.in_(PARTNERS)))
    assert all(row.grantable_by is None for row in rows)


async def _restrict(session, code: str) -> Permission:
    """Pretend `code` may reach staff only through the superadmin."""
    await session.execute(
        update(Permission)
        .where(Permission.code == code)
        .values(grantable_by={"staff": ["superadmin"]})
    )
    await session.commit()
    return await session.get(Permission, code)


async def test_grantable_by_blocks_other_grantors(session, make_user) -> None:
    gm = await make_user(Role.GENERAL_MANAGER)
    staff = await make_user(Role.STAFF)
    perm = await _restrict(session, "suppliers.view")
    gm_perms = await service.effective_permissions(session, gm)
    assert service.block_reason(gm, gm_perms, staff, perm) == "PERMISSION_GRANT_RESTRICTED"
    with pytest.raises(AppError) as e:
        await service.grant(session, gm, staff, "suppliers.view")
    assert e.value.code == "PERMISSION_GRANT_RESTRICTED"


async def test_grantable_by_exempts_the_superadmin(session, superadmin, make_user) -> None:
    staff = await make_user(Role.STAFF)
    perm = await _restrict(session, "suppliers.view")
    perms = await service.effective_permissions(session, superadmin)
    assert service.block_reason(superadmin, perms, staff, perm) is None
    await service.grant(session, superadmin, staff, "suppliers.view")


async def test_grantable_by_ignores_unlisted_target_roles(session, make_user) -> None:
    gm = await make_user(Role.GENERAL_MANAGER)
    sup = await make_user(Role.SUPERVISOR)
    perm = await _restrict(session, "suppliers.view")
    gm_perms = await service.effective_permissions(session, gm)
    assert service.block_reason(gm, gm_perms, sup, perm) is None


def test_features_must_not_use_restricted_permissions() -> None:
    """Feature levels bypass per-permission grant rules, so a feature can't use grantable_by."""
    restricted = registry.PermissionDef(
        code="suppliers.view",
        module="partners",
        name_en="x",
        name_km="x",
        description_en="x",
        description_km="x",
        assignable_to=(Role.GENERAL_MANAGER, Role.SUPERVISOR, Role.STAFF),
        grantable_by={Role.STAFF: (Role.SUPERADMIN,)},
    )
    perms = [p for p in registry.PERMISSIONS if p.code != "suppliers.view"] + [restricted]
    with pytest.raises(registry.FeatureRegistryError, match="grantable_by"):
        registry.validate_features(permissions=perms)
