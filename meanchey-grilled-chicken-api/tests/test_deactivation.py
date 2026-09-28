from app.models import Role
from tests.conftest import DEFAULT_PASSWORD, assert_error, auth


async def test_deactivated_user_is_fully_blocked(client, make_user) -> None:
    gm = await make_user(Role.GENERAL_MANAGER)
    sup = await make_user(Role.SUPERVISOR, "sup_to_remove")

    tokens = (
        await client.post(
            "/auth/login", json={"username": "sup_to_remove", "password": DEFAULT_PASSWORD}
        )
    ).json()
    access = {"Authorization": f"Bearer {tokens['access_token']}"}

    r = await client.post(f"/users/{sup.id}/deactivate", headers=auth(gm))
    assert r.status_code == 200
    assert r.json()["is_active"] is False
    assert r.json()["deleted_at"] is not None

    # Existing access token stops working immediately.
    assert_error(await client.get("/auth/me", headers=access), 401, "ACCOUNT_DISABLED")
    # Refresh tokens were revoked.
    r = await client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert_error(r, 401, "INVALID_REFRESH_TOKEN")
    # Login is refused.
    r = await client.post(
        "/auth/login", json={"username": "sup_to_remove", "password": DEFAULT_PASSWORD}
    )
    assert_error(r, 403, "ACCOUNT_DISABLED")
    # Wrong password on a deactivated account doesn't reveal its state.
    r = await client.post("/auth/login", json={"username": "sup_to_remove", "password": "nope"})
    assert_error(r, 401, "INVALID_CREDENTIALS")


async def test_reactivate(client, make_user) -> None:
    gm = await make_user(Role.GENERAL_MANAGER)
    sup = await make_user(Role.SUPERVISOR, "sup_back", is_active=False)
    r = await client.post(f"/users/{sup.id}/reactivate", headers=auth(gm))
    assert r.status_code == 200
    assert r.json()["is_active"] is True
    r = await client.post(
        "/auth/login", json={"username": "sup_back", "password": DEFAULT_PASSWORD}
    )
    assert r.status_code == 200


async def test_reactivate_conflicting_username(client, make_user) -> None:
    gm = await make_user(Role.GENERAL_MANAGER)
    old = await make_user(Role.STAFF, "same_name", is_active=False)
    await make_user(Role.STAFF, "same_name")
    r = await client.post(f"/users/{old.id}/reactivate", headers=auth(gm))
    assert_error(r, 409, "DUPLICATE_TELEGRAM_USERNAME")


async def test_inactive_users_hidden_by_default(client, make_user) -> None:
    gm = await make_user(Role.GENERAL_MANAGER)
    await make_user(Role.STAFF, "active_staff")
    await make_user(Role.STAFF, "gone_staff", is_active=False)
    names = lambda r: {u["telegram_username"] for u in r.json()["items"]}  # noqa: E731
    assert names(await client.get("/users", headers=auth(gm))) == {"active_staff"}
    r = await client.get("/users", params={"status": "inactive"}, headers=auth(gm))
    assert names(r) == {"gone_staff"}
    r = await client.get("/users", params={"status": "all"}, headers=auth(gm))
    assert names(r) == {"active_staff", "gone_staff"}
