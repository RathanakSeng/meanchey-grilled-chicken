"""Role hierarchy: who may act on whom, for every role."""

import pytest

from app.models import Role
from tests.conftest import assert_error, auth


@pytest.fixture
async def world(superadmin, make_user) -> dict:
    gm = await make_user(Role.GENERAL_MANAGER, "world_gm")
    sup1 = await make_user(Role.SUPERVISOR, "world_sup1")
    sup2 = await make_user(Role.SUPERVISOR, "world_sup2")
    staff1 = await make_user(Role.STAFF, "world_staff1")
    staff2 = await make_user(Role.STAFF, "world_staff2")
    return {
        "superadmin": superadmin,
        "gm": gm,
        "sup1": sup1,
        "sup2": sup2,
        "staff1": staff1,
        "staff2": staff2,
    }


OK, SCOPE, PERM = 200, "FORBIDDEN_SCOPE", "MISSING_PERMISSION"
# The superadmin is hidden from everyone else: looking it up is "not found", not "forbidden".
HIDDEN = "USER_NOT_FOUND"

VIEW_MATRIX = [
    # superadmin manages everyone below it
    ("superadmin", "superadmin", SCOPE),
    ("superadmin", "gm", OK),
    ("superadmin", "sup1", OK),
    ("superadmin", "staff1", OK),
    # general manager manages supervisors and staff
    ("gm", "superadmin", HIDDEN),
    ("gm", "gm", SCOPE),
    ("gm", "sup1", OK),
    ("gm", "staff1", OK),
    # supervisor manages staff only
    ("sup1", "superadmin", HIDDEN),
    ("sup1", "gm", SCOPE),
    ("sup1", "sup1", SCOPE),
    ("sup1", "sup2", SCOPE),
    ("sup1", "staff1", OK),
    # staff manage nobody (and hold no permissions)
    ("staff1", "superadmin", PERM),
    ("staff1", "gm", PERM),
    ("staff1", "sup1", PERM),
    ("staff1", "staff1", PERM),
    ("staff1", "staff2", PERM),
]


@pytest.mark.parametrize(("actor", "target", "expected"), VIEW_MATRIX)
async def test_view_scope(client, world, actor, target, expected) -> None:
    r = await client.get(f"/users/{world[target].id}", headers=auth(world[actor]))
    if expected == OK:
        assert r.status_code == 200, r.text
    else:
        assert_error(r, 404 if expected == HIDDEN else 403, expected)


@pytest.mark.parametrize(("actor", "target", "expected"), VIEW_MATRIX)
async def test_update_scope(client, world, actor, target, expected) -> None:
    r = await client.patch(
        f"/users/{world[target].id}", json={"full_name": "Renamed"}, headers=auth(world[actor])
    )
    if expected == OK:
        assert r.status_code == 200, r.text
    else:
        assert_error(r, 404 if expected == HIDDEN else 403, expected)


@pytest.mark.parametrize(
    ("actor", "roles"),
    [
        ("superadmin", {"general_manager", "supervisor", "staff"}),
        ("gm", {"supervisor", "staff"}),
        ("sup1", {"staff"}),
    ],
)
async def test_list_returns_only_users_in_scope(client, world, actor, roles) -> None:
    r = await client.get("/users", headers=auth(world[actor]))
    assert r.status_code == 200
    items = r.json()["items"]
    assert {u["role"] for u in items} == roles
    assert all(u["id"] != str(world[actor].id) for u in items)


async def test_list_filters(client, world, make_user) -> None:
    await make_user(Role.STAFF, "driver_one", position="driver")
    headers = auth(world["gm"])
    r = await client.get("/users", params={"role": "staff", "position": "driver"}, headers=headers)
    assert [u["telegram_username"] for u in r.json()["items"]] == ["driver_one"]
    r = await client.get("/users", params={"q": "SUP2"}, headers=headers)
    assert [u["telegram_username"] for u in r.json()["items"]] == ["world_sup2"]


async def test_staff_list_forbidden(client, world) -> None:
    assert_error(await client.get("/users", headers=auth(world["staff1"])), 403, PERM)


CREATE_MATRIX = [
    ("superadmin", "supervisor", 201),
    ("superadmin", "staff", 201),
    ("gm", "general_manager", SCOPE),
    ("gm", "supervisor", 201),
    ("gm", "staff", 201),
    ("sup1", "general_manager", SCOPE),
    ("sup1", "supervisor", SCOPE),
    ("sup1", "staff", 201),
    ("staff1", "staff", PERM),
]


@pytest.mark.parametrize(("actor", "role", "expected"), CREATE_MATRIX)
async def test_create_scope(client, world, actor, role, expected) -> None:
    body = {"role": role, "full_name": "New", "telegram_username": f"new_{role[:8]}"}
    if role == "staff":
        body["position"] = "worker"
    r = await client.post("/users", json=body, headers=auth(world[actor]))
    if expected == 201:
        assert r.status_code == 201, r.text
    else:
        assert_error(r, 403, expected)


async def test_supervisor_cannot_deactivate_without_permission(client, world) -> None:
    r = await client.post(f"/users/{world['staff1'].id}/deactivate", headers=auth(world["sup1"]))
    assert_error(r, 403, PERM)


async def test_supervisor_can_never_deactivate_users(client, world, make_user) -> None:
    # users.delete is general-manager only: a stored grant on a supervisor has no effect.
    sup = await make_user(Role.SUPERVISOR, "sup_deleter", perms=["users.view", "users.delete"])
    r = await client.post(f"/users/{world['staff1'].id}/deactivate", headers=auth(sup))
    assert_error(r, 403, PERM)
    me = (await client.get("/auth/me", headers=auth(sup))).json()
    assert "users.delete" not in me["permissions"]
