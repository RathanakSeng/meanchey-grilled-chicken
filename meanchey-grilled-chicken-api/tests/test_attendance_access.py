"""Attendance access: registry features and defaults, the default workplace (backfill and
assignment on create / edit / role change, the users list filter), the workplace guards."""

from sqlalchemy import select

from app.models import AttendanceWorkplace, AuditLog, Role
from app.permissions.registry import DEFAULT_PERMISSIONS, FEATURES_BY_CODE, MENUS
from tests.conftest import assert_error, auth, make_workplace

ALL_ATTENDANCE = {
    "attendance.view",
    "attendance.correct",
    "attendance.workplace_view",
    "attendance.workplace_update",
    "attendance.workplace_manage",
    "attendance.scheduling",
    "attendance.requests_review",
}


def test_registry() -> None:
    assert MENUS == ("workstation", "attendance", "settings")
    levels = {code: dict(FEATURES_BY_CODE[code].levels) for code in FEATURES_BY_CODE}
    assert levels["attendance"] == {"off": (), "view": ("attendance.view",)}
    assert levels["attendance_corrections"] == {"off": (), "full": ("attendance.correct",)}
    assert levels["attendance_workplace"] == {
        "off": (),
        "view": ("attendance.workplace_view",),
        "record": ("attendance.workplace_view", "attendance.workplace_update"),
        "full": (
            "attendance.workplace_view",
            "attendance.workplace_update",
            "attendance.workplace_manage",
        ),
    }
    assert FEATURES_BY_CODE["attendance_workplace"].applies_to == (Role.GENERAL_MANAGER,)
    scheduling = FEATURES_BY_CODE["attendance_scheduling"]
    assert scheduling.applies_to == (Role.GENERAL_MANAGER, Role.SUPERVISOR)
    assert scheduling.grantor_must_hold is True
    assert levels["attendance_scheduling"] == {"off": (), "full": ("attendance.scheduling",)}
    assert "attendance_shifts" not in FEATURES_BY_CODE
    gm = DEFAULT_PERMISSIONS[Role.GENERAL_MANAGER] & ALL_ATTENDANCE
    assert gm == {
        "attendance.view",
        "attendance.correct",
        "attendance.workplace_view",
        "attendance.requests_review",
    }
    assert not DEFAULT_PERMISSIONS[Role.SUPERVISOR] & ALL_ATTENDANCE
    assert not DEFAULT_PERMISSIONS[Role.STAFF] & ALL_ATTENDANCE


async def test_features_on_the_access_tab(client, make_user, superadmin) -> None:
    gm = await make_user(Role.GENERAL_MANAGER)
    sup = await make_user(Role.SUPERVISOR)
    menus = (await client.get(f"/users/{gm.id}/features", headers=auth(superadmin))).json()["menus"]
    attendance = next(m for m in menus if m["menu"] == "attendance")
    by_code = {f["code"]: f["current_level"] for f in attendance["features"]}
    assert by_code == {
        "attendance": "view",
        "attendance_corrections": "full",
        "attendance_workplace": "view",
        "attendance_scheduling": "off",
        "attendance_requests": "full",
    }
    menus = (await client.get(f"/users/{sup.id}/features", headers=auth(gm))).json()["menus"]
    attendance = next(m for m in menus if m["menu"] == "attendance")
    assert {f["code"] for f in attendance["features"]} == {
        "attendance",
        "attendance_corrections",
        "attendance_requests",
    }
    r = await client.put(
        f"/users/{sup.id}/features/attendance", json={"level": "view"}, headers=auth(gm)
    )
    assert r.status_code == 200, r.text
    # Staff never get attendance features (they check in without any permission).
    staff = await make_user(Role.STAFF)
    menus = (await client.get(f"/users/{staff.id}/features", headers=auth(gm))).json()["menus"]
    assert "attendance" not in {m["menu"] for m in menus}


async def test_default_workplace_assignment(client, session, superadmin, make_user) -> None:
    default = await session.scalar(
        select(AttendanceWorkplace).where(AttendanceWorkplace.is_default)
    )
    assert default.name == "Mean Chey" and default.latitude is None
    gm = await make_user(Role.GENERAL_MANAGER)
    body = {
        "role": "staff",
        "full_name": "Dara",
        "telegram_username": "dara_staff",
        "position": "Cook",
    }
    staff = (await client.post("/users", json=body, headers=auth(gm))).json()
    assert staff["workplace"] == {"id": str(default.id), "name": "Mean Chey"}
    # Promoted to supervisor: kept; to general manager: kept but unused (not tracked).
    r = await client.post(
        f"/users/{staff['id']}/role", json={"role": "supervisor"}, headers=auth(gm)
    )
    assert r.json()["workplace"]["id"] == str(default.id)
    r = await client.post(
        f"/users/{staff['id']}/role", json={"role": "general_manager"}, headers=auth(superadmin)
    )
    assert r.json()["workplace"]["id"] == str(default.id)
    # A GM can't be given one.
    assert_error(
        await client.patch(
            f"/users/{staff['id']}",
            json={"workplace_id": str(default.id)},
            headers=auth(superadmin),
        ),
        422,
        "VALIDATION_ERROR",
    )
    r = await client.post(
        f"/users/{staff['id']}/role",
        json={"role": "staff", "position": "Cook"},
        headers=auth(superadmin),
    )
    assert r.json()["workplace"]["id"] == str(default.id)
    # The GM itself has none.
    me = (await client.get("/auth/me", headers=auth(gm))).json()
    assert me["user"]["workplace"] is None


async def test_choose_and_move_workplace(client, session, superadmin, make_user) -> None:
    gm = await make_user(Role.GENERAL_MANAGER)
    branch = await make_workplace(session)
    body = {
        "role": "supervisor",
        "full_name": "Sokha",
        "telegram_username": "sokha_sup",
        "workplace_id": str(branch.id),
    }
    r = await client.post("/users", json=body, headers=auth(gm))
    assert r.status_code == 201, r.text
    sup = r.json()
    assert sup["workplace"] == {"id": str(branch.id), "name": "Branch 2"}
    # Users list filtered by workplace.
    r = await client.get(f"/users?workplace_id={branch.id}", headers=auth(gm))
    assert [u["id"] for u in r.json()["items"]] == [sup["id"]]
    # Moved back to the default in the edit (audited).
    default = await session.scalar(
        select(AttendanceWorkplace).where(AttendanceWorkplace.is_default)
    )
    r = await client.patch(
        f"/users/{sup['id']}", json={"workplace_id": str(default.id)}, headers=auth(gm)
    )
    assert r.json()["workplace"]["name"] == "Mean Chey"
    entry = await session.scalar(
        select(AuditLog).where(AuditLog.action == "user.update").order_by(AuditLog.id.desc())
    )
    assert entry.details["changes"]["workplace"] == ["Branch 2", "Mean Chey"]
    assert (await client.get(f"/users?workplace_id={branch.id}", headers=auth(gm))).json()[
        "items"
    ] == []
    # Role change with a workplace.
    r = await client.post(
        f"/users/{sup['id']}/role",
        json={"role": "staff", "position": "Cook", "workplace_id": str(branch.id)},
        headers=auth(gm),
    )
    assert r.json()["workplace"]["name"] == "Branch 2"
    # Unknown or archived workplaces are refused.
    import uuid

    body2 = {**body, "telegram_username": "x_sup", "workplace_id": str(uuid.uuid4())}
    assert_error(
        await client.post("/users", json=body2, headers=auth(gm)),
        404,
        "ATTENDANCE_WORKPLACE_NOT_FOUND",
    )
    branch.is_active = False
    await session.commit()
    body2["workplace_id"] = str(branch.id)
    assert_error(
        await client.post("/users", json=body2, headers=auth(gm)), 409, "WORKPLACE_ARCHIVED"
    )
    # Someone at an archived workplace moves to the default on reactivation.
    await client.post(f"/users/{sup['id']}/deactivate", headers=auth(gm))
    r = await client.post(f"/users/{sup['id']}/reactivate", headers=auth(gm))
    assert r.json()["workplace"]["name"] == "Mean Chey"


async def test_bootstrap_backfills_the_workplace(session, make_user) -> None:
    from app.bootstrap import bootstrap

    staff = await make_user(Role.STAFF)  # created directly: no workplace
    assert staff.workplace_id is None
    await bootstrap(session)
    await session.refresh(staff)
    assert staff.workplace_id is not None


async def test_workplace_guards(client, session, make_user, superadmin) -> None:
    gm = await make_user(Role.GENERAL_MANAGER)
    (wp,) = (await client.get("/attendance/workplaces", headers=auth(gm))).json()
    url = f"/attendance/workplaces/{wp['id']}"
    assert (await client.get(url, headers=auth(gm))).status_code == 200
    # View only: no edit, no create, no delete, no schedule.
    for method, path, body in (
        ("patch", url, {"radius_m": 150}),
        ("post", "/attendance/workplaces", {"name": "X"}),
        ("delete", url, None),
        ("post", f"{url}/restore", None),
    ):
        kwargs = {"json": body} if body is not None else {}
        r = await client.request(method.upper(), path, headers=auth(gm), **kwargs)
        assert_error(r, 403, "MISSING_PERMISSION")
    # The schedule endpoint is gone (Scheduling replaces it).
    r = await client.put(f"{url}/schedule", json={}, headers=auth(superadmin))
    assert r.status_code in (404, 405)
    # Staff can't see workplaces, nor can a GM with scheduling only (Scheduling has its own list).
    staff = await make_user(Role.STAFF)
    assert_error(
        await client.get("/attendance/workplaces", headers=auth(staff)), 403, "MISSING_PERMISSION"
    )
    other = await make_user(Role.GENERAL_MANAGER, perms=["attendance.scheduling"])
    assert_error(
        await client.get("/attendance/workplaces", headers=auth(other)), 403, "MISSING_PERMISSION"
    )
    nobody = await make_user(Role.GENERAL_MANAGER, perms=["users.view"])
    assert_error(
        await client.get("/attendance/workplaces", headers=auth(nobody)), 403, "MISSING_PERMISSION"
    )
    # The old global endpoints are gone.
    for path in ("/attendance/shifts", "/attendance/settings"):
        assert (await client.get(path, headers=auth(superadmin))).status_code == 404


async def test_workplace_options(client, session, make_user) -> None:
    """The user form's select and the users list filter: users.view or a workplace permission."""
    await make_workplace(session)
    sup = await make_user(Role.SUPERVISOR, perms=["users.view", "users.create"])
    r = await client.get("/attendance/workplace-options", headers=auth(sup))
    assert r.status_code == 200, r.text
    assert [(w["name"], w["is_default"]) for w in r.json()] == [
        ("Mean Chey", True),
        ("Branch 2", False),
    ]
    assert set(r.json()[0]) == {"id", "name", "is_default"}
    staff = await make_user(Role.STAFF)
    assert_error(
        await client.get("/attendance/workplace-options", headers=auth(staff)),
        403,
        "MISSING_PERMISSION",
    )
