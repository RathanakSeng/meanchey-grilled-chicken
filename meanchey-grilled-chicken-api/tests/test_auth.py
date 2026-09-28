from app.models import Role
from app.permissions.registry import PERMISSIONS
from tests.conftest import DEFAULT_PASSWORD, assert_error, auth


async def _login(client, username: str, password: str):
    return await client.post("/auth/login", json={"username": username, "password": password})


async def test_superadmin_login_does_not_require_password_change(client) -> None:
    r = await _login(client, "superadmin", "superadmin")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["must_change_password"] is False
    headers = {"Authorization": f"Bearer {body['access_token']}"}
    r = await client.get("/users", headers=headers)
    assert r.status_code == 200


async def test_superadmin_me_has_every_permission(client, superadmin) -> None:
    r = await client.get("/auth/me", headers=auth(superadmin))
    assert r.status_code == 200
    me = r.json()
    assert set(me["permissions"]) == {p.code for p in PERMISSIONS}
    assert me["manageable_roles"] == ["general_manager", "supervisor", "staff"]
    assert me["can_self_reset_password"] is True


async def test_wrong_password(client) -> None:
    assert_error(await _login(client, "superadmin", "nope"), 401, "INVALID_CREDENTIALS")
    assert_error(await _login(client, "nobody_here", "nope"), 401, "INVALID_CREDENTIALS")


async def test_new_user_must_change_password_on_first_login(client, superadmin) -> None:
    r = await client.post(
        "/users",
        json={"role": "general_manager", "full_name": "GM", "telegram_username": "the_gm"},
        headers=auth(superadmin),
    )
    assert r.status_code == 201
    assert r.json()["must_change_password"] is True

    r = await _login(client, "the_gm", "the_gm")
    assert r.status_code == 200
    assert r.json()["must_change_password"] is True
    headers = {"Authorization": f"Bearer {r.json()['access_token']}"}

    # Every endpoint except me / change-password / logout is blocked.
    assert_error(await client.get("/users", headers=headers), 403, "PASSWORD_CHANGE_REQUIRED")
    assert_error(
        await client.patch("/me", json={"language": "en"}, headers=headers),
        403,
        "PASSWORD_CHANGE_REQUIRED",
    )
    assert_error(await client.get("/permissions", headers=headers), 403, "PASSWORD_CHANGE_REQUIRED")
    assert (await client.get("/auth/me", headers=headers)).status_code == 200

    r = await client.post(
        "/auth/change-password",
        json={"current_password": "the_gm", "new_password": "short"},
        headers=headers,
    )
    assert_error(r, 422, "PASSWORD_TOO_SHORT")
    r = await client.post(
        "/auth/change-password",
        json={"current_password": "wrong", "new_password": "a-good-password"},
        headers=headers,
    )
    assert_error(r, 400, "WRONG_CURRENT_PASSWORD")

    r = await client.post(
        "/auth/change-password",
        json={"current_password": "the_gm", "new_password": "a-good-password"},
        headers=headers,
    )
    assert r.status_code == 204, r.text
    assert (await client.get("/users", headers=headers)).status_code == 200

    r = await _login(client, "the_gm", "a-good-password")
    assert r.json()["must_change_password"] is False


async def test_new_password_must_not_equal_username(client, make_user) -> None:
    user = await make_user(Role.SUPERVISOR, "long_username", must_change_password=True)
    r = await client.post(
        "/auth/change-password",
        json={"current_password": DEFAULT_PASSWORD, "new_password": "@Long_Username"},
        headers=auth(user),
    )
    assert_error(r, 422, "PASSWORD_EQUALS_USERNAME")


async def test_superadmin_new_password_must_not_equal_superadmin(client, superadmin) -> None:
    r = await client.post(
        "/auth/change-password",
        json={"current_password": "superadmin", "new_password": "SuperAdmin"},
        headers=auth(superadmin),
    )
    assert_error(r, 422, "PASSWORD_EQUALS_USERNAME")


async def test_refresh_rotates_tokens(client) -> None:
    tokens = (await _login(client, "superadmin", "superadmin")).json()
    r = await client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert r.status_code == 200, r.text
    new_tokens = r.json()
    assert new_tokens["refresh_token"] != tokens["refresh_token"]

    # The old refresh token is now revoked.
    r = await client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert_error(r, 401, "INVALID_REFRESH_TOKEN")
    r = await client.post("/auth/refresh", json={"refresh_token": new_tokens["refresh_token"]})
    assert r.status_code == 200


async def test_logout_revokes_refresh_token(client) -> None:
    tokens = (await _login(client, "superadmin", "superadmin")).json()
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    r = await client.post(
        "/auth/logout", json={"refresh_token": tokens["refresh_token"]}, headers=headers
    )
    assert r.status_code == 204
    r = await client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert_error(r, 401, "INVALID_REFRESH_TOKEN")


async def test_requests_without_or_with_bad_token(client) -> None:
    assert_error(await client.get("/auth/me"), 401, "NOT_AUTHENTICATED")
    r = await client.get("/auth/me", headers={"Authorization": "Bearer garbage"})
    assert_error(r, 401, "INVALID_TOKEN")


async def test_staff_can_edit_own_profile(client, make_user) -> None:
    staff = await make_user(Role.STAFF)
    r = await client.patch(
        "/me",
        json={"full_name": "New Name", "phone": "+855 12 345 678", "language": "en"},
        headers=auth(staff),
    )
    assert r.status_code == 200, r.text
    user = r.json()["user"]
    assert (user["full_name"], user["phone"], user["language"]) == (
        "New Name",
        "+855 12 345 678",
        "en",
    )
    assert r.json()["permissions"] == []
    assert r.json()["manageable_roles"] == []
