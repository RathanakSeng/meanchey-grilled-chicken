import pytest

from app.models import Role
from tests.conftest import assert_error, auth


async def _set(client, actor, gm, level: str):
    return await client.put(
        f"/users/{gm.id}/features/audit_log", json={"level": level}, headers=auth(actor)
    )


async def _level(client, superadmin, gm) -> str:
    menus = (await client.get(f"/users/{gm.id}/features", headers=auth(superadmin))).json()
    features = {f["code"]: f for m in menus["menus"] for f in m["features"]}
    return features["audit_log"]["current_level"]


async def test_superadmin_only_by_default_gm_when_allowed(client, superadmin, make_user) -> None:
    gm = await make_user(Role.GENERAL_MANAGER)  # role defaults: no audit.view
    await client.post(
        "/users",
        json={"role": "supervisor", "full_name": "Audited", "telegram_username": "audited_sup"},
        headers=auth(superadmin),
    )

    # The superadmin always sees the log, its own actions included.
    r = await client.get("/audit-logs", headers=auth(superadmin))
    assert r.status_code == 200, r.text
    entry = next(i for i in r.json()["items"] if i["action"] == "user.create")
    assert entry["actor"]["role"] == "superadmin"
    assert entry["target"]["telegram_username"] == "audited_sup"

    # A general manager: off by default.
    assert await _level(client, superadmin, gm) == "off"
    r = await client.get("/audit-logs", headers=auth(gm))
    assert_error(r, 403, "MISSING_PERMISSION")
    assert r.json()["error"]["details"]["required"] == ["audit.view"]

    # The superadmin switches it on: the GM sees the log, still without the superadmin's actions
    # (the user it created, the access change it just made).
    assert (await _set(client, superadmin, gm, "view")).status_code == 200
    assert await _level(client, superadmin, gm) == "view"
    r = await client.get("/audit-logs?page_size=100", headers=auth(gm))
    assert r.status_code == 200, r.text
    actions = {i["action"] for i in r.json()["items"]}
    assert not {"user.create", "feature.set", "permission.grant"} & actions
    assert all(i["actor"] is None or not i["actor"]["is_system"] for i in r.json()["items"])

    # Switched off again: gone.
    assert (await _set(client, superadmin, gm, "off")).status_code == 200
    assert_error(await client.get("/audit-logs", headers=auth(gm)), 403, "MISSING_PERMISSION")


async def test_only_the_superadmin_sets_it(client, superadmin, make_user) -> None:
    gm = await make_user(
        Role.GENERAL_MANAGER,
    )
    other = await make_user(Role.GENERAL_MANAGER)
    sup = await make_user(Role.SUPERVISOR)
    # GM only: a GM can't switch it on for another GM (or itself), nor for a supervisor.
    assert (await _set(client, gm, other, "view")).status_code == 403
    assert (await _set(client, gm, gm, "view")).status_code == 403
    assert (await _set(client, superadmin, sup, "view")).status_code in (403, 422)
    # Not assignable to a supervisor, even by the superadmin.
    r = await client.put(f"/users/{sup.id}/permissions/audit.view", headers=auth(superadmin))
    assert r.status_code >= 400, r.text


@pytest.mark.parametrize("role", [Role.SUPERVISOR, Role.STAFF])
async def test_supervisors_and_staff_refused(client, make_user, role) -> None:
    user = await make_user(role)
    assert_error(await client.get("/audit-logs", headers=auth(user)), 403, "MISSING_PERMISSION")


async def test_audit_log_filter_by_action(client, superadmin) -> None:
    await client.post("/auth/login", json={"username": "superadmin", "password": "bad"})
    await client.post("/auth/login", json={"username": "superadmin", "password": "superadmin"})
    r = await client.get(
        "/audit-logs", params={"action": "auth.login_failed"}, headers=auth(superadmin)
    )
    assert {i["action"] for i in r.json()["items"]} == {"auth.login_failed"}
    assert r.json()["total"] == 1
