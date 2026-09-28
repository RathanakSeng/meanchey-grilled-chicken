from datetime import timedelta

from app.models import Role, utcnow
from tests.conftest import DEFAULT_PASSWORD, assert_error, auth


async def _login(client, username: str, password: str):
    return await client.post("/auth/login", json={"username": username, "password": password})


async def test_gm_resets_staff_password(client, session, make_user) -> None:
    gm = await make_user(Role.GENERAL_MANAGER)
    staff = await make_user(Role.STAFF, "staff_forgot")
    tokens = (await _login(client, "staff_forgot", DEFAULT_PASSWORD)).json()

    # Also clears a lockout.
    staff.locked_until = utcnow() + timedelta(minutes=10)
    await session.commit()

    r = await client.post(f"/users/{staff.id}/reset-password", headers=auth(gm))
    assert r.status_code == 204, r.text

    r = await client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert_error(r, 401, "INVALID_REFRESH_TOKEN")
    assert_error(await _login(client, "staff_forgot", DEFAULT_PASSWORD), 401, "INVALID_CREDENTIALS")
    r = await _login(client, "staff_forgot", "staff_forgot")
    assert r.status_code == 200
    assert r.json()["must_change_password"] is True


async def test_superadmin_resets_gm_password(client, superadmin, make_user) -> None:
    await make_user(Role.GENERAL_MANAGER, "gm_forgot")
    gm = (await client.get("/users", headers=auth(superadmin))).json()["items"][0]
    r = await client.post(f"/users/{gm['id']}/reset-password", headers=auth(superadmin))
    assert r.status_code == 204
    r = await _login(client, "gm_forgot", "gm_forgot")
    assert r.json()["must_change_password"] is True


async def test_supervisor_cannot_reset_passwords(client, make_user) -> None:
    sup = await make_user(Role.SUPERVISOR, perms=["users.view", "users.update", "users.create"])
    staff = await make_user(Role.STAFF)
    r = await client.post(f"/users/{staff.id}/reset-password", headers=auth(sup))
    assert_error(r, 403, "MISSING_PERMISSION")


async def test_gm_cannot_reset_superadmin(client, superadmin, make_user) -> None:
    gm = await make_user(Role.GENERAL_MANAGER)
    r = await client.post(f"/users/{superadmin.id}/reset-password", headers=auth(gm))
    assert_error(r, 404, "USER_NOT_FOUND")


async def test_gm_self_reset(client, make_user) -> None:
    await make_user(Role.GENERAL_MANAGER, "gm_self")
    tokens = (await _login(client, "gm_self", DEFAULT_PASSWORD)).json()
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    me = (await client.get("/auth/me", headers=headers)).json()
    assert me["can_self_reset_password"] is True

    assert (await client.post("/me/reset-password", headers=headers)).status_code == 204
    r = await client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert_error(r, 401, "INVALID_REFRESH_TOKEN")
    r = await _login(client, "gm_self", "gm_self")
    assert r.status_code == 200
    assert r.json()["must_change_password"] is True


async def test_superadmin_self_reset_is_not_forced_to_change(client, superadmin) -> None:
    r = await client.post(
        "/auth/change-password",
        json={"current_password": "superadmin", "new_password": "a-strong-password"},
        headers=auth(superadmin),
    )
    assert r.status_code == 204
    assert (await client.post("/me/reset-password", headers=auth(superadmin))).status_code == 204
    r = await _login(client, "superadmin", "superadmin")
    assert r.status_code == 200
    assert r.json()["must_change_password"] is False


async def test_supervisor_and_staff_cannot_self_reset(client, make_user) -> None:
    for role in (Role.SUPERVISOR, Role.STAFF):
        user = await make_user(role)
        me = (await client.get("/auth/me", headers=auth(user))).json()
        assert me["can_self_reset_password"] is False
        r = await client.post("/me/reset-password", headers=auth(user))
        assert_error(r, 403, "MISSING_PERMISSION")
