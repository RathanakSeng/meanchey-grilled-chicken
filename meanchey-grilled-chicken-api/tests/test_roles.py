"""Promote / demote: POST /users/{id}/role."""

import pytest
from sqlalchemy import select

from app.models import AuditLog, Role, UserPermission
from app.permissions.registry import DEFAULT_PERMISSIONS
from tests.conftest import assert_error, auth


def _change(client, actor, target, role, position=None):
    body = {"role": role}
    if position is not None:
        body["position"] = position
    return client.post(f"/users/{target.id}/role", json=body, headers=auth(actor))


async def _stored(session, user) -> set[str]:
    return set(
        await session.scalars(
            select(UserPermission.permission_code).where(UserPermission.user_id == user.id)
        )
    )


async def test_gm_promotes_staff_to_supervisor(client, session, make_user) -> None:
    gm = await make_user(Role.GENERAL_MANAGER)
    staff = await make_user(Role.STAFF, position="Grill cook", perms=["suppliers.view"])
    r = await _change(client, gm, staff, "supervisor")
    assert r.status_code == 200, r.text
    assert r.json()["role"] == "supervisor"
    assert r.json()["position"] is None
    # Access replaced by the supervisor defaults (every feature at Full).
    assert await _stored(session, staff) == set(DEFAULT_PERMISSIONS[Role.SUPERVISOR])
    me = (await client.get("/auth/me", headers=auth(staff))).json()
    assert "users.view" in me["permissions"]

    log = await session.scalar(select(AuditLog).where(AuditLog.action == "user.role_change"))
    assert log.actor_id == gm.id and log.target_user_id == staff.id
    assert log.details["from"] == "staff" and log.details["to"] == "supervisor"
    assert log.details["position_from"] == "Grill cook" and log.details["position_to"] is None


async def test_gm_demotes_supervisor_to_staff(client, session, make_user) -> None:
    gm = await make_user(Role.GENERAL_MANAGER)
    sup = await make_user(Role.SUPERVISOR)
    assert_error(await _change(client, gm, sup, "staff"), 422, "POSITION_REQUIRED")
    r = await _change(client, gm, sup, "staff", position="  Cashier ")
    assert r.status_code == 200, r.text
    assert r.json()["role"] == "staff"
    assert r.json()["position"] == "Cashier"
    assert await _stored(session, sup) == set()  # staff: every feature Off
    assert_error(await client.get("/users", headers=auth(sup)), 403, "MISSING_PERMISSION")


async def test_position_only_for_staff(client, make_user) -> None:
    gm = await make_user(Role.GENERAL_MANAGER)
    staff = await make_user(Role.STAFF)
    assert_error(
        await _change(client, gm, staff, "supervisor", position="x"), 422, "POSITION_NOT_ALLOWED"
    )


async def test_same_role_is_a_noop(client, session, make_user) -> None:
    gm = await make_user(Role.GENERAL_MANAGER)
    sup = await make_user(Role.SUPERVISOR, perms=["suppliers.view"])
    assert (await _change(client, gm, sup, "supervisor")).status_code == 200
    assert await _stored(session, sup) == {"suppliers.view"}  # untouched
    assert (
        await session.scalar(select(AuditLog).where(AuditLog.action == "user.role_change")) is None
    )


@pytest.mark.parametrize("role", ["general_manager", "superadmin"])
async def test_gm_cannot_promote_above_supervisor(client, make_user, role) -> None:
    gm = await make_user(Role.GENERAL_MANAGER)
    sup = await make_user(Role.SUPERVISOR)
    r = await _change(client, gm, sup, role)
    assert_error(r, 403, "FORBIDDEN_SCOPE")
    assert "superadmin" not in r.text


async def test_gm_cannot_change_itself_or_the_hidden_account(client, superadmin, make_user) -> None:
    gm = await make_user(Role.GENERAL_MANAGER)
    assert_error(await _change(client, gm, gm, "supervisor"), 403, "FORBIDDEN_SCOPE")
    assert_error(await _change(client, gm, superadmin, "supervisor"), 404, "USER_NOT_FOUND")


async def test_supervisor_cannot_change_roles(client, make_user) -> None:
    sup = await make_user(Role.SUPERVISOR, perms=["users.view", "users.create", "users.update"])
    staff = await make_user(Role.STAFF)
    other = await make_user(Role.SUPERVISOR)
    assert_error(await _change(client, sup, staff, "supervisor"), 403, "FORBIDDEN_SCOPE")
    assert_error(await _change(client, sup, other, "staff", "x"), 403, "FORBIDDEN_SCOPE")


async def test_staff_cannot_change_roles(client, make_user) -> None:
    staff = await make_user(Role.STAFF)
    other = await make_user(Role.STAFF)
    assert_error(await _change(client, staff, other, "supervisor"), 403, "MISSING_PERMISSION")


async def test_superadmin_promotes_and_demotes_everyone_below(
    client, session, superadmin, make_user
) -> None:
    gm = await make_user(Role.GENERAL_MANAGER)
    sup = await make_user(Role.SUPERVISOR)
    staff = await make_user(Role.STAFF)

    # Promoting needs a free general manager slot.
    await make_user(Role.GENERAL_MANAGER)  # 2 of 2
    assert_error(
        await _change(client, superadmin, sup, "general_manager"), 409, "ROLE_LIMIT_REACHED"
    )

    assert (await _change(client, superadmin, gm, "supervisor")).status_code == 200
    r = await _change(client, superadmin, sup, "general_manager")
    assert r.status_code == 200, r.text
    assert await _stored(session, sup) == set(DEFAULT_PERMISSIONS[Role.GENERAL_MANAGER])
    me = (await client.get("/auth/me", headers=auth(sup))).json()
    assert me["can_manage_features"] is True

    assert (await _change(client, superadmin, staff, "general_manager")).status_code == 409
    assert (await _change(client, superadmin, gm, "staff", "Driver")).status_code == 200


async def test_inactive_gm_does_not_block_a_promotion(client, superadmin, make_user) -> None:
    await make_user(Role.GENERAL_MANAGER, is_active=False)
    sup = await make_user(Role.SUPERVISOR)
    assert (await _change(client, superadmin, sup, "general_manager")).status_code == 200
