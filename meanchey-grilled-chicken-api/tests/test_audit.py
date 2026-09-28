from app.models import Role
from tests.conftest import assert_error, auth


async def test_audit_log_visible_to_superadmin_and_gm_only(client, superadmin, make_user) -> None:
    gm = await make_user(Role.GENERAL_MANAGER, perms=[])  # role-based, not permission-based
    sup = await make_user(Role.SUPERVISOR)
    await client.post(
        "/users",
        json={"role": "supervisor", "full_name": "Audited", "telegram_username": "audited_sup"},
        headers=auth(superadmin),
    )

    # The superadmin sees its own actions.
    r = await client.get("/audit-logs", headers=auth(superadmin))
    assert r.status_code == 200, r.text
    entry = next(i for i in r.json()["items"] if i["action"] == "user.create")
    assert entry["actor"]["role"] == "superadmin"
    assert entry["target"]["telegram_username"] == "audited_sup"

    # The general manager can open the log but doesn't see what the superadmin did.
    r = await client.get("/audit-logs", headers=auth(gm))
    assert r.status_code == 200, r.text
    assert not any(i["action"] == "user.create" for i in r.json()["items"])

    assert_error(await client.get("/audit-logs", headers=auth(sup)), 403, "FORBIDDEN_ROLE")


async def test_audit_log_filter_by_action(client, superadmin) -> None:
    await client.post("/auth/login", json={"username": "superadmin", "password": "bad"})
    await client.post("/auth/login", json={"username": "superadmin", "password": "superadmin"})
    r = await client.get(
        "/audit-logs", params={"action": "auth.login_failed"}, headers=auth(superadmin)
    )
    assert {i["action"] for i in r.json()["items"]} == {"auth.login_failed"}
    assert r.json()["total"] == 1
