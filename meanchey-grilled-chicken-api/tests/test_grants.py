from sqlalchemy import select

from app.models import AuditLog, Role
from tests.conftest import assert_error, auth


def _grant(client, actor, target, code):
    return client.put(f"/users/{target.id}/permissions/{code}", headers=auth(actor))


def _revoke(client, actor, target, code):
    return client.delete(f"/users/{target.id}/permissions/{code}", headers=auth(actor))


async def _perms(client, user) -> list[str]:
    return (await client.get("/auth/me", headers=auth(user))).json()["permissions"]


async def test_gm_grants_and_revokes_supervisor_permission(client, make_user) -> None:
    gm = await make_user(Role.GENERAL_MANAGER)
    sup = await make_user(Role.SUPERVISOR)
    assert "users.delete" not in await _perms(client, sup)

    assert (await _grant(client, gm, sup, "users.delete")).status_code == 204
    assert "users.delete" in await _perms(client, sup)
    # Idempotent.
    assert (await _grant(client, gm, sup, "users.delete")).status_code == 204

    assert (await _revoke(client, gm, sup, "users.delete")).status_code == 204
    assert "users.delete" not in await _perms(client, sup)


async def test_superadmin_grants_to_gm(client, superadmin, make_user) -> None:
    gm = await make_user(Role.GENERAL_MANAGER, perms=[])
    assert (await _grant(client, superadmin, gm, "users.reset_password")).status_code == 204
    assert await _perms(client, gm) == ["users.reset_password"]


async def test_cannot_grant_what_you_do_not_hold(client, superadmin, make_user) -> None:
    gm = await make_user(Role.GENERAL_MANAGER)
    sup = await make_user(Role.SUPERVISOR)
    assert (await _revoke(client, superadmin, gm, "users.delete")).status_code == 204
    assert_error(await _grant(client, gm, sup, "users.delete"), 403, "PERMISSION_NOT_HELD")
    # Nor revoke it.
    assert_error(await _revoke(client, gm, sup, "users.delete"), 403, "PERMISSION_NOT_HELD")


async def test_cannot_grant_outside_scope(client, make_user) -> None:
    gm = await make_user(Role.GENERAL_MANAGER)
    sup1 = await make_user(Role.SUPERVISOR, perms=["users.view", "permissions.grant"])
    sup2 = await make_user(Role.SUPERVISOR)
    assert_error(await _grant(client, sup1, sup2, "users.view"), 403, "FORBIDDEN_SCOPE")
    assert_error(await _grant(client, sup1, gm, "users.view"), 403, "FORBIDDEN_SCOPE")
    assert_error(await _grant(client, gm, gm, "users.view"), 403, "FORBIDDEN_SCOPE")


async def test_assignable_to_is_respected(client, superadmin, make_user) -> None:
    gm = await make_user(Role.GENERAL_MANAGER)
    sup = await make_user(Role.SUPERVISOR)
    staff = await make_user(Role.STAFF)
    # Password reset is reserved for the general manager.
    assert_error(
        await _grant(client, gm, sup, "users.reset_password"), 422, "PERMISSION_NOT_ASSIGNABLE"
    )
    assert_error(
        await _grant(client, superadmin, sup, "users.reset_password"),
        422,
        "PERMISSION_NOT_ASSIGNABLE",
    )
    # No Phase 1 permission is assignable to staff.
    assert_error(await _grant(client, gm, staff, "users.view"), 422, "PERMISSION_NOT_ASSIGNABLE")


async def test_grant_requires_permissions_grant(client, make_user) -> None:
    sup = await make_user(Role.SUPERVISOR)  # defaults: no permissions.grant
    staff = await make_user(Role.STAFF)
    assert_error(await _grant(client, sup, staff, "users.view"), 403, "MISSING_PERMISSION")


async def test_unknown_permission(client, make_user) -> None:
    gm = await make_user(Role.GENERAL_MANAGER)
    sup = await make_user(Role.SUPERVISOR)
    assert_error(await _grant(client, gm, sup, "nope.nothing"), 404, "PERMISSION_NOT_FOUND")


async def test_revoke_does_not_cascade_but_is_surfaced(
    client, session, superadmin, make_user
) -> None:
    gm = await make_user(Role.GENERAL_MANAGER)
    sup = await make_user(Role.SUPERVISOR, perms=[])
    assert (await _grant(client, gm, sup, "users.view")).status_code == 204

    assert (await _revoke(client, superadmin, gm, "users.view")).status_code == 204
    # The supervisor keeps the permission the GM granted.
    assert "users.view" in await _perms(client, sup)

    log = await session.scalar(
        select(AuditLog)
        .where(AuditLog.action == "permission.revoke", AuditLog.target_user_id == gm.id)
        .order_by(AuditLog.id.desc())
    )
    assert log is not None
    assert [d["user_id"] for d in log.details["downstream_grants"]] == [str(sup.id)]


async def test_permission_matrix_editability(client, superadmin, make_user) -> None:
    gm = await make_user(Role.GENERAL_MANAGER)
    sup = await make_user(Role.SUPERVISOR)
    await _revoke(client, superadmin, gm, "users.delete")

    r = await client.get(f"/users/{sup.id}/permissions", headers=auth(gm))
    assert r.status_code == 200, r.text
    perms = {p["code"]: p for m in r.json()["modules"] for p in m["permissions"]}
    # users.reset_password is not assignable to supervisors, so it isn't listed.
    assert set(perms) == {
        "users.view",
        "users.create",
        "users.update",
        "users.delete",
        "permissions.grant",
    }
    assert perms["users.view"]["granted"] is True
    assert perms["users.view"]["can_edit"] is True
    assert perms["users.delete"]["can_edit"] is False  # GM no longer holds it
    assert perms["users.delete"]["granted"] is False


async def test_permission_catalog(client, superadmin) -> None:
    r = await client.get("/permissions", headers=auth(superadmin))
    assert r.status_code == 200
    (module,) = r.json()
    assert module["module"] == "users"
    assert module["name_km"]
    assert len(module["permissions"]) == 6
