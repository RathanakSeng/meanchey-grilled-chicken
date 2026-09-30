"""Role limits: defaults, enforcement on create / reactivate / change role, concurrency, settings
endpoints (superadmin only), capacity for managers, and several general managers."""

import asyncio
import uuid

import pytest
from sqlalchemy import select

from app.models import AuditLog, Notification, Role, RoleLimit
from app.models.role_limit import DEFAULT_ROLE_LIMITS
from tests.conftest import assert_error, auth
from tests.test_production import PRODUCED, Api, ok


def _body(role: str, name: str | None = None) -> dict:
    name = name or f"u_{uuid.uuid4().hex[:10]}"
    body = {"role": role, "full_name": name, "telegram_username": name}
    if role == "staff":
        body["position"] = "Grill cook"
    return body


async def _create(client, actor, role: str, name: str | None = None):
    return await client.post("/users", json=_body(role, name), headers=auth(actor))


async def _set(client, actor, role: str, max_active):
    return await client.put(
        f"/settings/role-limits/{role}", json={"max_active": max_active}, headers=auth(actor)
    )


async def _fill(make_user, role: Role, n: int) -> list:
    return [await make_user(role) for _ in range(n)]


# --- Defaults ------------------------------------------------------------------------------------


async def test_defaults_are_seeded(session) -> None:
    rows = {r.role: r.max_active for r in await session.scalars(select(RoleLimit))}
    assert rows == {"general_manager": 2, "supervisor": 3, "staff": 10}
    assert DEFAULT_ROLE_LIMITS == {
        Role.GENERAL_MANAGER: 2,
        Role.SUPERVISOR: 3,
        Role.STAFF: 10,
    }


async def test_limits_listing(client, superadmin, make_user) -> None:
    await _fill(make_user, Role.SUPERVISOR, 2)
    await make_user(Role.STAFF, is_active=False)  # inactive users don't count
    r = await client.get("/settings/role-limits", headers=auth(superadmin))
    rows = {row["role"]: row for row in ok(r)}
    assert set(rows) == {"general_manager", "supervisor", "staff"}  # never the superadmin
    assert {k: (v["max_active"], v["active"], v["over_limit"]) for k, v in rows.items()} == {
        "general_manager": (2, 0, False),
        "supervisor": (3, 2, False),
        "staff": (10, 0, False),
    }
    assert rows["staff"]["updated_by"] is None


# --- Enforcement ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("role", "actor_role", "limit"),
    [
        ("general_manager", Role.SUPERADMIN, 2),
        ("supervisor", Role.GENERAL_MANAGER, 3),
        ("staff", Role.GENERAL_MANAGER, 10),
        ("staff", Role.SUPERVISOR, 10),
    ],
)
async def test_create_is_blocked_at_the_limit(
    client, superadmin, make_user, role, actor_role, limit
) -> None:
    if actor_role == Role.SUPERADMIN:
        actor = superadmin
    elif actor_role == Role.SUPERVISOR:
        # Adding staff needs the Record level of staff management (not a supervisor default).
        actor = await make_user(actor_role, perms=["users.view", "users.create"])
    else:
        actor = await make_user(actor_role)
    already = 1 if Role(role) == actor_role else 0  # the acting GM / supervisor counts too
    for _ in range(limit - already):
        assert (await _create(client, actor, role)).status_code == 201
    r = await _create(client, actor, role)
    assert_error(r, 409, "ROLE_LIMIT_REACHED")
    assert r.json()["error"]["details"] == {"role": role, "limit": limit, "active": limit}
    assert "superadmin" not in r.text.lower()


async def test_deactivating_frees_a_slot_and_reactivation_rechecks(client, make_user) -> None:
    gm = await make_user(Role.GENERAL_MANAGER)
    sups = await _fill(make_user, Role.SUPERVISOR, 3)
    assert_error(await _create(client, gm, "supervisor"), 409, "ROLE_LIMIT_REACHED")

    r = await client.post(f"/users/{sups[0].id}/deactivate", headers=auth(gm))
    assert r.status_code == 200, r.text
    assert (await _create(client, gm, "supervisor")).status_code == 201  # took the freed slot
    r = await client.post(f"/users/{sups[0].id}/reactivate", headers=auth(gm))
    assert_error(r, 409, "ROLE_LIMIT_REACHED")
    assert r.json()["error"]["details"] == {"role": "supervisor", "limit": 3, "active": 3}


async def test_change_role_checks_only_the_new_role(client, make_user) -> None:
    gm = await make_user(Role.GENERAL_MANAGER)
    await _fill(make_user, Role.SUPERVISOR, 3)
    staff = await make_user(Role.STAFF)
    body = {"role": "supervisor"}
    r = await client.post(f"/users/{staff.id}/role", json=body, headers=auth(gm))
    assert_error(r, 409, "ROLE_LIMIT_REACHED")
    # Staff is full too: demoting a supervisor into it is refused; into a free role it works.
    await _fill(make_user, Role.STAFF, 9)  # 10 of 10
    sup = await make_user(Role.SUPERVISOR)  # 4 (direct insert, above the limit)
    r = await client.post(
        f"/users/{sup.id}/role", json={"role": "staff", "position": "Driver"}, headers=auth(gm)
    )
    assert_error(r, 409, "ROLE_LIMIT_REACHED")
    # The same role again is a no-op, even when the role is full.
    r = await client.post(f"/users/{staff.id}/role", json={"role": "staff"}, headers=auth(gm))
    assert r.status_code == 200, r.text


async def test_inactive_user_changes_role_without_a_slot(client, make_user) -> None:
    gm = await make_user(Role.GENERAL_MANAGER)
    await _fill(make_user, Role.SUPERVISOR, 3)
    gone = await make_user(Role.STAFF, is_active=False)
    r = await client.post(f"/users/{gone.id}/role", json={"role": "supervisor"}, headers=auth(gm))
    assert r.status_code == 200, r.text
    # ...but reactivating it then needs one.
    r = await client.post(f"/users/{gone.id}/reactivate", headers=auth(gm))
    assert_error(r, 409, "ROLE_LIMIT_REACHED")


async def test_only_one_request_takes_the_last_slot(client, make_user) -> None:
    gm = await make_user(Role.GENERAL_MANAGER)
    await _fill(make_user, Role.SUPERVISOR, 2)  # one slot left
    results = await asyncio.gather(*(_create(client, gm, "supervisor") for _ in range(6)))
    codes = sorted(r.status_code for r in results)
    assert codes == [201, 409, 409, 409, 409, 409]
    assert all(
        r.json()["error"]["code"] == "ROLE_LIMIT_REACHED" for r in results if r.status_code == 409
    )


# --- Settings ------------------------------------------------------------------------------------


async def test_unlimited_for_supervisor_and_staff(client, superadmin, make_user) -> None:
    gm = await make_user(Role.GENERAL_MANAGER)
    await _fill(make_user, Role.SUPERVISOR, 3)
    rows = ok(await _set(client, superadmin, "supervisor", None))
    sup = next(r for r in rows if r["role"] == "supervisor")
    assert (sup["max_active"], sup["over_limit"]) == (None, False)
    assert sup["updated_by"]["id"] == str(superadmin.id)
    assert (await _create(client, gm, "supervisor")).status_code == 201


@pytest.mark.parametrize(
    ("role", "value"),
    [
        ("general_manager", None),
        ("general_manager", 0),
        ("supervisor", 0),
        ("staff", -1),
        ("staff", 1000),
        ("superadmin", 1),
    ],
)
async def test_limit_validation(client, superadmin, role, value) -> None:
    assert_error(await _set(client, superadmin, role, value), 422, "VALIDATION_ERROR")


async def test_lowering_below_the_active_count(client, session, superadmin, make_user) -> None:
    gm = await make_user(Role.GENERAL_MANAGER)
    sups = await _fill(make_user, Role.SUPERVISOR, 3)
    rows = ok(await _set(client, superadmin, "supervisor", 1))
    sup = next(r for r in rows if r["role"] == "supervisor")
    assert (sup["max_active"], sup["active"], sup["over_limit"]) == (1, 3, True)
    # Nobody is deactivated; nobody new gets in until enough leave.
    for s in sups:
        await session.refresh(s)
        assert s.is_active
    assert_error(await _create(client, gm, "supervisor"), 409, "ROLE_LIMIT_REACHED")
    for s in sups[:2]:
        assert (await client.post(f"/users/{s.id}/deactivate", headers=auth(gm))).status_code == 200
    assert_error(await _create(client, gm, "supervisor"), 409, "ROLE_LIMIT_REACHED")  # 1 of 1
    await client.post(f"/users/{sups[2].id}/deactivate", headers=auth(gm))
    assert (await _create(client, gm, "supervisor")).status_code == 201


async def test_settings_are_superadmin_only(client, make_user) -> None:
    for role in (Role.GENERAL_MANAGER, Role.SUPERVISOR, Role.STAFF):
        user = await make_user(role)
        r = await client.get("/settings/role-limits", headers=auth(user))
        assert_error(r, 403, "FORBIDDEN_ROLE")
        assert_error(await _set(client, user, "staff", 20), 403, "FORBIDDEN_ROLE")


async def test_limit_change_is_audited_and_hidden_from_gms(
    client, session, superadmin, make_user
) -> None:
    gm = await make_user(Role.GENERAL_MANAGER)
    ok(await _set(client, superadmin, "staff", 12))
    ok(await _set(client, superadmin, "staff", 12))  # same value again: nothing written
    logs = list(
        await session.scalars(
            select(AuditLog).where(AuditLog.action == "settings.role_limit_update")
        )
    )
    assert [(log.actor_id, log.details) for log in logs] == [
        (superadmin.id, {"role": "staff", "from": 10, "to": 12})
    ]
    items = ok(await client.get("/audit-logs?page_size=100", headers=auth(gm)))["items"]
    assert all(i["action"] != "settings.role_limit_update" for i in items)


# --- Capacity ------------------------------------------------------------------------------------


async def test_capacity_lists_only_managed_roles(client, superadmin, make_user) -> None:
    gm = await make_user(Role.GENERAL_MANAGER)
    sup = await make_user(Role.SUPERVISOR)
    await _fill(make_user, Role.STAFF, 10)
    ok(await _set(client, superadmin, "supervisor", None))

    async def capacity(user) -> dict:
        rows = ok(await client.get("/users/role-capacity", headers=auth(user)))
        return {r["role"]: (r["active"], r["limit"], r["full"]) for r in rows}

    assert await capacity(superadmin) == {
        "general_manager": (1, 2, False),
        "supervisor": (1, None, False),
        "staff": (10, 10, True),
    }
    assert await capacity(gm) == {"supervisor": (1, None, False), "staff": (10, 10, True)}
    assert await capacity(sup) == {"staff": (10, 10, True)}
    staff = await make_user(Role.STAFF)
    assert_error(
        await client.get("/users/role-capacity", headers=auth(staff)), 403, "MISSING_PERMISSION"
    )


async def test_capacity_with_create_only(client, make_user) -> None:
    sup = await make_user(Role.SUPERVISOR, perms=["users.create"])
    assert ok(await client.get("/users/role-capacity", headers=auth(sup)))[0]["role"] == "staff"


# --- Several general managers --------------------------------------------------------------------


async def test_two_gms_cannot_act_on_each_other(client, make_user) -> None:
    gm1 = await make_user(Role.GENERAL_MANAGER)
    gm2 = await make_user(Role.GENERAL_MANAGER)
    h = auth(gm1)
    calls = [
        client.get(f"/users/{gm2.id}", headers=h),
        client.patch(f"/users/{gm2.id}", json={"full_name": "x"}, headers=h),
        client.post(f"/users/{gm2.id}/deactivate", headers=h),
        client.post(f"/users/{gm2.id}/reset-password", headers=h),
        client.post(f"/users/{gm2.id}/role", json={"role": "supervisor"}, headers=h),
        client.get(f"/users/{gm2.id}/features", headers=h),
        client.put(f"/users/{gm2.id}/features/suppliers", json={"level": "off"}, headers=h),
    ]
    for call in calls:
        r = await call
        assert_error(r, 403, "FORBIDDEN_SCOPE")
    # Neither lists the other.
    items = ok(await client.get("/users?status=all&page_size=100", headers=h))["items"]
    assert str(gm2.id) not in {i["id"] for i in items}


async def test_both_gms_get_alerts_and_see_the_same_audit_log(client, session, make_user) -> None:
    gm1 = await make_user(Role.GENERAL_MANAGER)
    gm2 = await make_user(Role.GENERAL_MANAGER)
    supplier = ok(
        await client.post("/suppliers", json={"name": "Sokha Farm"}, headers=auth(gm1)), 201
    )
    api = Api(client, gm1)
    batch = await api.step1(supplier)
    batch = ok(await api.patch(batch, "produced", **PRODUCED))
    ok(await api.finish(batch, "produced"))
    recipients = set(
        await session.scalars(
            select(Notification.user_id).where(
                Notification.type == "production.processing_finished"
            )
        )
    )
    assert {gm1.id, gm2.id} <= recipients

    def actions(items):
        return [(i["action"], i["created_at"]) for i in items]

    log1 = ok(await client.get("/audit-logs?page_size=100", headers=auth(gm1)))["items"]
    log2 = ok(await client.get("/audit-logs?page_size=100", headers=auth(gm2)))["items"]
    assert actions(log1) == actions(log2) and log1
