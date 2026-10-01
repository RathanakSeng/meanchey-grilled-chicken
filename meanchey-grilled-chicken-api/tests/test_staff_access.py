"""Supervisors set staff access (users.manage_access), capped by their own access; adding and
editing staff are separate staff management levels (View only / Record / Full access)."""

import pytest
from sqlalchemy import delete, select

from app.bootstrap import bootstrap
from app.models import AuditLog, Permission, Role, UserPermission
from app.permissions import registry
from app.permissions.registry import DEFAULT_PERMISSIONS, FEATURES_BY_CODE
from tests.conftest import assert_error, auth

MANAGE = "users.manage_access"
STAFF_MGMT = FEATURES_BY_CODE["staff_management"]
STAFF_ACCESS = FEATURES_BY_CODE["staff_access"]


def _set(client, actor, target, feature, level):
    return client.put(
        f"/users/{target.id}/features/{feature}", json={"level": level}, headers=auth(actor)
    )


async def _features(client, actor, target) -> dict[str, dict]:
    return await _features_of(client, actor, target.id)


async def _features_of(client, actor, user_id) -> dict[str, dict]:
    r = await client.get(f"/users/{user_id}/features", headers=auth(actor))
    assert r.status_code == 200, r.text
    return {f["code"]: f for m in r.json()["menus"] for f in m["features"]}


def _allowed(feature: dict) -> dict[str, bool]:
    return {lv["level"]: lv["allowed"] for lv in feature["levels"]}


async def _me(client, user) -> dict:
    return (await client.get("/auth/me", headers=auth(user))).json()


def _staff_body(username: str) -> dict:
    return {
        "role": "staff",
        "full_name": username,
        "telegram_username": username,
        "position": "worker",
    }


# --- Registry and defaults -----------------------------------------------------------------------


def test_registry() -> None:
    registry.validate_features()
    perm = next(p for p in registry.PERMISSIONS if p.code == MANAGE)
    assert perm.assignable_to == (Role.SUPERVISOR,)
    grant = next(p for p in registry.PERMISSIONS if p.code == "permissions.grant")
    assert grant.assignable_to == (Role.GENERAL_MANAGER,)  # never supervisors
    assert STAFF_ACCESS.menu == "settings"
    assert STAFF_ACCESS.applies_to == (Role.SUPERVISOR,)
    assert STAFF_ACCESS.level_map == {"off": frozenset(), "full": {MANAGE}}
    assert STAFF_MGMT.level_map["record"] == {"users.view", "users.create"}


def test_defaults() -> None:
    sup = DEFAULT_PERMISSIONS[Role.SUPERVISOR]
    assert sup & STAFF_MGMT.codes == {"users.view"}  # View only
    assert MANAGE in sup  # Staff access Full
    assert MANAGE not in DEFAULT_PERMISSIONS[Role.GENERAL_MANAGER]
    assert DEFAULT_PERMISSIONS[Role.STAFF] == frozenset()


async def test_gm_created_supervisor_gets_staff_access(client, make_user) -> None:
    gm = await make_user(Role.GENERAL_MANAGER)
    body = {"role": "supervisor", "full_name": "New sup", "telegram_username": "new_sup"}
    r = await client.post("/users", json=body, headers=auth(gm))
    assert r.status_code == 201, r.text
    features = await _features_of(client, gm, r.json()["id"])
    assert features["staff_access"]["current_level"] == "full"
    assert features["staff_management"]["current_level"] == "view"


async def test_backfill_gives_manage_access_to_active_supervisors_only(session, make_user) -> None:
    gm = await make_user(Role.GENERAL_MANAGER)
    sup = await make_user(Role.SUPERVISOR)
    gone = await make_user(Role.SUPERVISOR, is_active=False)
    staff = await make_user(Role.STAFF)
    # As before this feature was deployed.
    await session.execute(delete(UserPermission).where(UserPermission.permission_code == MANAGE))
    await session.execute(delete(Permission).where(Permission.code == MANAGE))
    await session.execute(delete(AuditLog))
    await session.commit()

    await bootstrap(session)

    holders = set(
        await session.scalars(
            select(UserPermission.user_id).where(UserPermission.permission_code == MANAGE)
        )
    )
    assert holders == {sup.id}
    assert not {gm.id, gone.id, staff.id} & holders
    log = await session.scalar(select(AuditLog).where(AuditLog.target_user_id == sup.id))
    assert log.actor_id is None
    assert log.details == {"permission": MANAGE, "source": "default_backfill"}


# --- Supervisor sets staff access ----------------------------------------------------------------


async def test_supervisor_sets_staff_levels_within_its_own(client, session, make_user) -> None:
    sup = await make_user(Role.SUPERVISOR)  # defaults: suppliers/customers/production Full
    staff = await make_user(Role.STAFF)

    features = await _features(client, sup, staff)
    assert set(features) == {"suppliers", "customers", "production", "inventory"}
    assert all(f["can_edit"] for f in features.values())
    assert all(all(_allowed(f).values()) for f in features.values())

    for feature, level in (("suppliers", "full"), ("customers", "view"), ("production", "record")):
        r = await _set(client, sup, staff, feature, level)
        assert r.status_code == 200, r.text
        assert r.json()["current_level"] == level
    assert (await _set(client, sup, staff, "customers", "off")).status_code == 200

    log = await session.scalar(
        select(AuditLog)
        .where(AuditLog.action == "feature.set", AuditLog.target_user_id == staff.id)
        .order_by(AuditLog.id)
    )
    assert log.actor_id == sup.id


async def test_supervisor_cannot_give_more_than_it_has(client, session, make_user) -> None:
    sup = await make_user(
        Role.SUPERVISOR, perms=[MANAGE, "users.view", "suppliers.view", "production.view"]
    )
    staff = await make_user(Role.STAFF)

    features = await _features(client, sup, staff)
    assert _allowed(features["suppliers"]) == {"off": True, "view": True, "full": False}
    assert _allowed(features["customers"]) == {"off": True, "view": False, "full": False}
    assert _allowed(features["production"]) == {
        "off": True,
        "view": True,
        "record": False,
        "full": False,
    }
    # can_edit is about the target; the per-level cap is in `allowed`.
    assert all(f["can_edit"] for f in features.values())

    r = await _set(client, sup, staff, "suppliers", "full")
    assert_error(r, 403, "PERMISSION_NOT_HELD")
    assert r.json()["error"]["details"] == {"feature": "suppliers", "level": "full"}
    assert_error(await _set(client, sup, staff, "production", "record"), 403, "PERMISSION_NOT_HELD")
    assert_error(await _set(client, sup, staff, "customers", "view"), 403, "PERMISSION_NOT_HELD")
    stored = set(
        await session.scalars(
            select(UserPermission.permission_code).where(UserPermission.user_id == staff.id)
        )
    )
    assert stored == set()

    assert (await _set(client, sup, staff, "suppliers", "view")).status_code == 200
    assert (await _set(client, sup, staff, "customers", "off")).status_code == 200


async def test_supervisor_can_lower_a_level_above_its_own(client, make_user) -> None:
    """Staff set higher by the GM can still be lowered (or switched off) by the supervisor."""
    gm = await make_user(Role.GENERAL_MANAGER)
    sup = await make_user(Role.SUPERVISOR, perms=[MANAGE, "users.view", "suppliers.view"])
    staff = await make_user(Role.STAFF)
    assert (await _set(client, gm, staff, "suppliers", "full")).status_code == 200
    assert (await _features(client, sup, staff))["suppliers"]["current_level"] == "full"
    assert (await _set(client, sup, staff, "suppliers", "view")).status_code == 200
    assert (await _set(client, sup, staff, "suppliers", "off")).status_code == 200


async def test_check_order_for_supervisors(client, superadmin, make_user) -> None:
    sup = await make_user(Role.SUPERVISOR, perms=[MANAGE, "users.view"])
    other = await make_user(Role.SUPERVISOR)
    gm = await make_user(Role.GENERAL_MANAGER)
    staff = await make_user(Role.STAFF)
    inactive = await make_user(Role.STAFF, is_active=False)

    # Scope: other supervisors and general managers are out of reach, the superadmin hidden.
    for target in (other, gm, sup):
        assert_error(
            await client.get(f"/users/{target.id}/features", headers=auth(sup)),
            403,
            "FORBIDDEN_SCOPE",
        )
        assert_error(await _set(client, sup, target, "suppliers", "off"), 403, "FORBIDDEN_SCOPE")
    assert_error(await _set(client, sup, superadmin, "suppliers", "off"), 404, "USER_NOT_FOUND")

    assert_error(await _set(client, sup, staff, "nope", "full"), 404, "FEATURE_NOT_FOUND")
    assert_error(
        await _set(client, sup, staff, "staff_access", "full"), 422, "FEATURE_NOT_APPLICABLE"
    )
    assert_error(await _set(client, sup, staff, "suppliers", "nope"), 422, "VALIDATION_ERROR")
    # The cap comes before USER_INACTIVE.
    assert_error(await _set(client, sup, inactive, "suppliers", "view"), 403, "PERMISSION_NOT_HELD")
    assert_error(await _set(client, sup, inactive, "suppliers", "off"), 409, "USER_INACTIVE")


async def test_gm_lowering_a_supervisor_does_not_cascade(client, session, make_user) -> None:
    gm = await make_user(Role.GENERAL_MANAGER)
    sup = await make_user(Role.SUPERVISOR)
    staff = await make_user(Role.STAFF)
    assert (await _set(client, sup, staff, "suppliers", "full")).status_code == 200

    assert (await _set(client, gm, sup, "suppliers", "view")).status_code == 200
    # Staff keep what the supervisor gave them...
    assert (await _features(client, gm, staff))["suppliers"]["current_level"] == "full"
    # ...but the supervisor can't give Full again.
    await _set(client, sup, staff, "suppliers", "off")
    assert_error(await _set(client, sup, staff, "suppliers", "full"), 403, "PERMISSION_NOT_HELD")


async def test_staff_access_off(client, make_user) -> None:
    gm = await make_user(Role.GENERAL_MANAGER)
    sup = await make_user(Role.SUPERVISOR)
    staff = await make_user(Role.STAFF)
    assert (await _set(client, gm, sup, "staff_access", "off")).status_code == 200

    assert (await _me(client, sup))["can_manage_features"] is False
    assert_error(
        await client.get(f"/users/{staff.id}/features", headers=auth(sup)),
        403,
        "MISSING_PERMISSION",
    )
    r = await _set(client, sup, staff, "suppliers", "view")
    assert_error(r, 403, "MISSING_PERMISSION")
    assert r.json()["error"]["details"] == {"required": ["permissions.grant", MANAGE]}
    # Still sees staff (staff management View only).
    assert (await client.get("/users", headers=auth(sup))).status_code == 200


async def test_supervisor_never_uses_detailed_permissions(client, make_user) -> None:
    sup = await make_user(Role.SUPERVISOR)
    staff = await make_user(Role.STAFF)
    assert_error(
        await client.get(f"/users/{staff.id}/permissions", headers=auth(sup)), 403, "FORBIDDEN_ROLE"
    )
    assert "permissions.grant" not in (await _me(client, sup))["permissions"]


async def test_gm_behavior_unchanged(client, make_user) -> None:
    gm = await make_user(Role.GENERAL_MANAGER, perms=["permissions.grant"])
    sup = await make_user(Role.SUPERVISOR)
    features = await _features(client, gm, sup)
    assert set(features) >= {"staff_management", "staff_access"}
    assert all(all(_allowed(f).values()) for f in features.values())
    for level in ("record", "full", "view", "off"):
        assert (await _set(client, gm, sup, "staff_management", level)).status_code == 200
    assert (await _set(client, gm, sup, "staff_access", "off")).status_code == 200
    assert (await _set(client, gm, sup, "staff_access", "full")).status_code == 200


# --- Adding and editing staff --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("level", "can_create", "can_update"),
    [("view", False, False), ("record", True, False), ("full", True, True)],
)
async def test_staff_management_levels(client, make_user, level, can_create, can_update) -> None:
    gm = await make_user(Role.GENERAL_MANAGER)
    sup = await make_user(Role.SUPERVISOR)
    staff = await make_user(Role.STAFF)
    assert (await _set(client, gm, sup, "staff_management", level)).status_code == 200

    assert (await client.get(f"/users/{staff.id}", headers=auth(sup))).status_code == 200
    r = await client.post("/users", json=_staff_body(f"lvl_{level}"), headers=auth(sup))
    if can_create:
        assert r.status_code == 201, r.text
    else:
        assert_error(r, 403, "MISSING_PERMISSION")
    r = await client.patch(f"/users/{staff.id}", json={"full_name": "Renamed"}, headers=auth(sup))
    if can_update:
        assert r.status_code == 200, r.text
    else:
        assert_error(r, 403, "MISSING_PERMISSION")


async def test_record_level_still_applies_the_role_limit(client, superadmin, make_user) -> None:
    sup = await make_user(Role.SUPERVISOR, perms=["users.view", "users.create"])
    r = await client.put(
        "/settings/role-limits/staff", json={"max_active": 1}, headers=auth(superadmin)
    )
    assert r.status_code == 200, r.text
    assert (
        await client.post("/users", json=_staff_body("rlimit_a"), headers=auth(sup))
    ).status_code == 201
    assert_error(
        await client.post("/users", json=_staff_body("rlimit_b"), headers=auth(sup)),
        409,
        "ROLE_LIMIT_REACHED",
    )


async def test_gm_reads_as_full_staff_management(client, superadmin, make_user) -> None:
    gm = await make_user(Role.GENERAL_MANAGER)
    features = await _features(client, superadmin, gm)
    assert features["staff_management"]["current_level"] == "full"
    assert "staff_access" not in features
    assert (await _set(client, superadmin, gm, "staff_management", "record")).status_code == 200
    assert (await _features(client, superadmin, gm))["staff_management"][
        "current_level"
    ] == "record"
