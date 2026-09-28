"""Detailed permissions: the superadmin's tool. Everyone else uses feature levels."""

import pytest
from sqlalchemy import select

from app.models import AuditLog, Role
from app.permissions.sync import sync_registry
from tests.conftest import assert_error, auth


def _grant(client, actor, target, code):
    return client.put(f"/users/{target.id}/permissions/{code}", headers=auth(actor))


def _revoke(client, actor, target, code):
    return client.delete(f"/users/{target.id}/permissions/{code}", headers=auth(actor))


async def _perms(client, user) -> list[str]:
    return (await client.get("/auth/me", headers=auth(user))).json()["permissions"]


@pytest.mark.parametrize("role", [Role.GENERAL_MANAGER, Role.SUPERVISOR, Role.STAFF])
async def test_detailed_permission_endpoints_are_superadmin_only(client, make_user, role) -> None:
    actor = await make_user(role)
    staff = await make_user(Role.STAFF)
    calls = [
        client.get("/permissions", headers=auth(actor)),
        client.get(f"/users/{staff.id}/permissions", headers=auth(actor)),
        _grant(client, actor, staff, "suppliers.view"),
        _revoke(client, actor, staff, "suppliers.view"),
    ]
    for call in calls:
        r = await call
        assert_error(r, 403, "FORBIDDEN_ROLE")
        assert "details" not in r.json()["error"]  # no list of allowed roles


async def test_superadmin_grants_and_revokes(client, superadmin, make_user) -> None:
    sup = await make_user(Role.SUPERVISOR, perms=[])
    assert "suppliers.view" not in await _perms(client, sup)

    assert (await _grant(client, superadmin, sup, "suppliers.view")).status_code == 204
    assert "suppliers.view" in await _perms(client, sup)
    # Idempotent.
    assert (await _grant(client, superadmin, sup, "suppliers.view")).status_code == 204

    assert (await _revoke(client, superadmin, sup, "suppliers.view")).status_code == 204
    assert "suppliers.view" not in await _perms(client, sup)


async def test_superadmin_grants_to_gm(client, superadmin, make_user) -> None:
    gm = await make_user(Role.GENERAL_MANAGER, perms=[])
    assert (await _grant(client, superadmin, gm, "users.reset_password")).status_code == 204
    assert await _perms(client, gm) == ["users.reset_password"]


async def test_superadmin_cannot_target_itself(client, superadmin) -> None:
    assert_error(await _grant(client, superadmin, superadmin, "users.view"), 403, "FORBIDDEN_SCOPE")


@pytest.mark.parametrize(
    ("role", "code"),
    [
        (Role.SUPERVISOR, "users.reset_password"),
        (Role.SUPERVISOR, "users.delete"),  # supervisors never deactivate users
        (Role.SUPERVISOR, "permissions.grant"),  # supervisors never grant
        (Role.STAFF, "users.view"),
    ],
)
async def test_assignable_to_is_respected(client, superadmin, make_user, role, code) -> None:
    target = await make_user(role)
    assert_error(await _grant(client, superadmin, target, code), 422, "PERMISSION_NOT_ASSIGNABLE")


async def test_existing_supervisor_grant_permission_is_ineffective(
    client, session, make_user
) -> None:
    """A supervisor granted permissions.grant before this change keeps the row, not the power."""
    sup = await make_user(Role.SUPERVISOR, perms=["users.view", "permissions.grant"])
    staff = await make_user(Role.STAFF)
    await sync_registry(session)
    await session.commit()

    me = (await client.get("/auth/me", headers=auth(sup))).json()
    assert "permissions.grant" not in me["permissions"]
    assert me["can_manage_features"] is False
    r = await client.put(
        f"/users/{staff.id}/features/suppliers", json={"level": "view"}, headers=auth(sup)
    )
    assert_error(r, 403, "MISSING_PERMISSION")


async def test_unknown_permission(client, superadmin, make_user) -> None:
    sup = await make_user(Role.SUPERVISOR)
    assert_error(await _grant(client, superadmin, sup, "nope.nothing"), 404, "PERMISSION_NOT_FOUND")


async def test_revoke_does_not_cascade_but_is_surfaced(
    client, session, superadmin, make_user
) -> None:
    gm = await make_user(Role.GENERAL_MANAGER)
    sup = await make_user(Role.SUPERVISOR, perms=[])
    # The GM gives the supervisor access through a feature level (granted_by = GM).
    r = await client.put(
        f"/users/{sup.id}/features/suppliers", json={"level": "view"}, headers=auth(gm)
    )
    assert r.status_code == 200, r.text

    assert (await _revoke(client, superadmin, gm, "suppliers.view")).status_code == 204
    # The supervisor keeps the permission the GM granted.
    assert "suppliers.view" in await _perms(client, sup)

    log = await session.scalar(
        select(AuditLog)
        .where(AuditLog.action == "permission.revoke", AuditLog.target_user_id == gm.id)
        .order_by(AuditLog.id.desc())
    )
    assert log is not None
    assert [d["user_id"] for d in log.details["downstream_grants"]] == [str(sup.id)]


async def test_permission_matrix(client, superadmin, make_user) -> None:
    sup = await make_user(Role.SUPERVISOR)
    r = await client.get(f"/users/{sup.id}/permissions", headers=auth(superadmin))
    assert r.status_code == 200, r.text
    perms = {p["code"]: p for m in r.json()["modules"] for p in m["permissions"]}
    # Only what a supervisor can hold: no reset_password, delete or grant.
    assert {c for c in perms if c.startswith(("users.", "permissions."))} == {
        "users.view",
        "users.create",
        "users.update",
    }
    assert perms["users.view"]["granted"] is True
    assert all(p["can_edit"] is True and p["reason"] is None for p in perms.values())


async def test_permission_matrix_inactive_target(client, superadmin, make_user) -> None:
    sup = await make_user(Role.SUPERVISOR, is_active=False)
    r = await client.get(f"/users/{sup.id}/permissions", headers=auth(superadmin))
    perms = [p for m in r.json()["modules"] for p in m["permissions"]]
    assert all(p["can_edit"] is False and p["reason"] == "USER_INACTIVE" for p in perms)


async def test_permission_catalog(client, superadmin) -> None:
    r = await client.get("/permissions", headers=auth(superadmin))
    assert r.status_code == 200
    users, partners = r.json()
    assert users["module"] == "users"
    assert users["name_km"]
    assert len(users["permissions"]) == 6
    assert partners["module"] == "partners"
    assert partners["name_km"] == "ដៃគូ"
    assert [p["code"] for p in partners["permissions"]] == [
        "suppliers.view",
        "suppliers.create",
        "suppliers.update",
        "suppliers.delete",
        "customers.view",
        "customers.create",
        "customers.update",
        "customers.delete",
    ]
