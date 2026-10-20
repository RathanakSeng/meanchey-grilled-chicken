"""Workplaces: CRUD (copying the default schedule, default switch, delete / archive / restore),
the read-only schedule summary, and check-in / `me/today` evaluated with the employee's own
workplace. Schedule changes are in test_attendance_scheduling.py."""

from sqlalchemy import select

from app.models import (
    AttendanceRecord,
    AttendanceScheduleVersion,
    AttendanceWorkplace,
    AuditLog,
    Role,
    User,
)
from tests.conftest import (
    assert_error,
    at,
    auth,
    branch_position,
    make_workplace,
    position,
    set_schedule,
)


async def _default(session) -> AttendanceWorkplace:
    return await session.scalar(select(AttendanceWorkplace).where(AttendanceWorkplace.is_default))


async def _audit(session, action: str) -> list[AuditLog]:
    return list(
        await session.scalars(
            select(AuditLog).where(AuditLog.action == action).order_by(AuditLog.id)
        )
    )


async def test_list_shows_rules_shifts_and_counts(client, session, make_user, workplace) -> None:
    gm = await make_user(Role.GENERAL_MANAGER)
    await make_user(Role.STAFF, workplace_id=workplace.id)
    await make_user(Role.SUPERVISOR, workplace_id=workplace.id)
    await make_user(Role.STAFF, workplace_id=workplace.id, is_active=False)
    branch = await make_workplace(session)
    (default, other) = (await client.get("/attendance/workplaces", headers=auth(gm))).json()
    assert (default["name"], default["is_default"], default["employee_count"]) == (
        "Mean Chey",
        True,
        2,
    )
    schedule = default["schedule"]
    assert schedule["open_before_min"] == 30 and schedule["max_accuracy_m"] == 100
    assert schedule["weekdays"] == [1, 2, 3, 4, 5, 6, 7]
    assert default["employees"] is None and default["timezone"] == "Asia/Phnom_Penh"
    morning = schedule["shifts"][0]
    assert (morning["start_time"], morning["end_time"]) == ("07:00", "12:00")
    assert morning["windows"] == {
        "check_in_opens": "06:30",
        "check_in_until": "07:44",
        "late_after": "07:00",
        "absent_from": "07:45",
        "check_out_opens": "12:00",
        "check_out_until": "12:59",
        "forgot_from": "13:00",
    }
    assert other["id"] == str(branch.id)
    assert other["schedule"]["shifts"][0]["windows"]["check_in_opens"] == "07:45"
    assert other["schedule"]["shifts"][1]["windows"]["absent_from"] == "13:50"
    assert other["employee_count"] == 0
    # The detail lists the active employees.
    detail = (await client.get(f"/attendance/workplaces/{default['id']}", headers=auth(gm))).json()
    assert len(detail["employees"]) == 2
    assert detail["employees"][0]["role"] == "supervisor"


async def test_create_copies_the_default_schedule(client, session, superadmin, clock) -> None:
    default = await _default(session)
    await set_schedule(
        session,
        default,
        open_before_min=20,
        weekdays=[1, 2, 3, 4, 5, 6],
        shift_times={"afternoon": ("13:30", "15:00")},
    )
    body = {
        "name": "  Toul  Kork ",
        "address": "St 1",
        "latitude": 11.58,
        "longitude": 104.9,
        "radius_m": 150,
    }
    r = await client.post("/attendance/workplaces", json=body, headers=auth(superadmin))
    assert r.status_code == 201, r.text
    out = r.json()
    assert (out["name"], out["is_default"], out["radius_m"], out["has_coordinates"]) == (
        "Toul Kork",
        False,
        150,
        True,
    )
    assert out["schedule"]["open_before_min"] == 20
    assert out["schedule"]["weekdays"] == [1, 2, 3, 4, 5, 6]
    assert [s["start_time"] for s in out["schedule"]["shifts"]] == ["07:00", "13:30"]
    # A version of its own, from today (the server's date).
    assert out["schedule"]["effective_from"] == "2026-10-13"
    versions = list(
        await session.scalars(
            select(AttendanceScheduleVersion).where(
                AttendanceScheduleVersion.workplace_id == out["id"]
            )
        )
    )
    assert len(versions) == 1 and versions[0].created_by == superadmin.id
    assert out["created_by"]["id"] == str(superadmin.id)
    (entry,) = await _audit(session, "workplace.create")
    assert entry.details["schedule_from"] == "Mean Chey"
    # Names are unique among active workplaces (case-insensitive).
    r = await client.post(
        "/attendance/workplaces", json={"name": "toul kork"}, headers=auth(superadmin)
    )
    assert_error(r, 409, "WORKPLACE_NAME_TAKEN")
    for bad in ({"name": " "}, {"name": "X", "latitude": 11.5}, {"name": "X", "radius_m": 5}):
        r = await client.post("/attendance/workplaces", json=bad, headers=auth(superadmin))
        assert_error(r, 422, "VALIDATION_ERROR")


async def test_update_and_default_switch(client, session, superadmin) -> None:
    default = await _default(session)
    url = f"/attendance/workplaces/{default.id}"
    body = {"latitude": 11.5621084, "longitude": 104.8885351, "radius_m": 150, "address": " St 1 "}
    r = await client.patch(url, json=body, headers=auth(superadmin))
    assert r.status_code == 200, r.text
    out = r.json()
    assert (out["latitude"], out["longitude"]) == (11.562108, 104.888535)
    assert (out["radius_m"], out["address"], out["has_coordinates"]) == (150, "St 1", True)
    assert out["updated_by"]["id"] == str(superadmin.id)
    (entry,) = await _audit(session, "workplace.update")
    assert set(entry.details["changes"]) == {"latitude", "longitude", "radius_m", "address"}
    for bad in (
        {"latitude": 11.5},
        {"latitude": 91, "longitude": 104},
        {"radius_m": 5},
        {"radius_m": 5001},
        {"name": " "},
        {"is_default": False},
    ):
        assert_error(
            await client.patch(url, json=bad, headers=auth(superadmin)), 422, "VALIDATION_ERROR"
        )

    # A workplace without a location can't become the default.
    bare = (
        await client.post("/attendance/workplaces", json={"name": "Bare"}, headers=auth(superadmin))
    ).json()
    r = await client.patch(
        f"/attendance/workplaces/{bare['id']}", json={"is_default": True}, headers=auth(superadmin)
    )
    assert_error(r, 422, "VALIDATION_ERROR")
    branch = await make_workplace(session)
    r = await client.patch(
        f"/attendance/workplaces/{branch.id}", json={"is_default": True}, headers=auth(superadmin)
    )
    assert r.json()["is_default"] is True
    listed = (await client.get("/attendance/workplaces", headers=auth(superadmin))).json()
    assert [w["name"] for w in listed if w["is_default"]] == ["Branch 2"]
    entry = (await _audit(session, "workplace.update"))[-1]
    assert entry.details["changes"]["previous_default"] == ["Mean Chey", None]
    # Renaming onto another active name is refused.
    r = await client.patch(url, json={"name": "branch 2"}, headers=auth(superadmin))
    assert_error(r, 409, "WORKPLACE_NAME_TAKEN")


async def test_delete_archive_restore(client, session, superadmin, make_user, clock) -> None:
    default = await _default(session)
    assert_error(
        await client.delete(f"/attendance/workplaces/{default.id}", headers=auth(superadmin)),
        409,
        "WORKPLACE_IS_DEFAULT",
    )
    # Without history: deleted; inactive employees there lose the link.
    empty = await make_workplace(session, "Empty")
    gone = await make_user(Role.STAFF, workplace_id=empty.id, is_active=False)
    r = await client.delete(f"/attendance/workplaces/{empty.id}", headers=auth(superadmin))
    assert r.json() == {"result": "deleted"}
    assert await session.get(AttendanceWorkplace, empty.id, populate_existing=True) is None
    await session.refresh(gone)
    assert gone.workplace_id is None
    assert len(await _audit(session, "workplace.delete")) == 1

    # Active employees assigned: refused with the count.
    branch = await make_workplace(session)
    staff = await make_user(Role.STAFF, workplace_id=branch.id)
    r = await client.delete(f"/attendance/workplaces/{branch.id}", headers=auth(superadmin))
    assert_error(r, 409, "WORKPLACE_IN_USE")
    assert r.json()["error"]["details"]["employees"] == 1

    # With attendance history: archived, records keep their workplace.
    clock(at("08:05"))
    r = await client.post("/attendance/check-in", json=branch_position(), headers=auth(staff))
    assert r.status_code == 200, r.text
    staff.workplace_id = default.id
    await session.commit()
    r = await client.delete(f"/attendance/workplaces/{branch.id}", headers=auth(superadmin))
    assert r.json() == {"result": "archived"}
    record = await session.scalar(select(AttendanceRecord))
    assert record.workplace_id == branch.id
    listed = (await client.get("/attendance/workplaces", headers=auth(superadmin))).json()
    assert [w["name"] for w in listed] == ["Mean Chey"]
    listed = (
        await client.get("/attendance/workplaces?include_archived=true", headers=auth(superadmin))
    ).json()
    archived = next(w for w in listed if w["name"] == "Branch 2")
    assert archived["is_active"] is False and archived["archived_at"] and archived["has_history"]
    # Archived: no edits or schedule changes; its name is free again.
    url = f"/attendance/workplaces/{branch.id}"
    assert_error(
        await client.patch(url, json={"radius_m": 200}, headers=auth(superadmin)),
        409,
        "WORKPLACE_ARCHIVED",
    )
    assert_error(
        await client.put(
            "/attendance/scheduling/weekdays",
            json={"workplace_ids": [str(branch.id)], "weekdays": [1, 2, 3]},
            headers=auth(superadmin),
        ),
        409,
        "WORKPLACE_ARCHIVED",
    )
    taken = await make_workplace(session, "Branch 2", metres_north=9000)
    assert_error(
        await client.post(f"{url}/restore", headers=auth(superadmin)), 409, "WORKPLACE_NAME_TAKEN"
    )
    taken.name = "Branch 3"
    await session.commit()
    r = await client.post(f"{url}/restore", headers=auth(superadmin))
    assert r.status_code == 200, r.text
    assert (r.json()["is_active"], r.json()["archived_at"]) == (True, None)
    assert [len(await _audit(session, a)) for a in ("workplace.archive", "workplace.restore")] == [
        1,
        1,
    ]


async def test_check_in_uses_the_employees_workplace(
    client, session, make_user, workplace, clock
) -> None:
    branch = await make_workplace(session)
    here = await make_user(Role.STAFF, workplace_id=workplace.id)
    there = await make_user(Role.STAFF, workplace_id=branch.id)
    # 07:40: the default's check-in is open, the branch's opens at 07:45.
    clock(at("07:40"))
    today = (await client.get("/attendance/me/today", headers=auth(there))).json()
    assert today["workplace"]["name"] == "Branch 2" and today["max_accuracy_m"] == 50
    assert today["next_action"]["action"] == "none"
    assert today["next_action"]["next_opens_at"] == at("07:45").isoformat()
    r = await client.post("/attendance/check-in", json=branch_position(), headers=auth(there))
    assert_error(r, 409, "ATTENDANCE_TOO_EARLY")
    # Same time, the default workplace (start 07:00): late 40 min.
    r = await client.post("/attendance/check-in", json=position(), headers=auth(here))
    assert r.json()["record"]["late_minutes"] == 40
    # The default workplace's position is too far for the branch's employee (5 km).
    clock(at("07:50"))
    r = await client.post("/attendance/check-in", json=position(), headers=auth(there))
    assert_error(r, 422, "ATTENDANCE_TOO_FAR")
    # The branch's own accuracy limit (50 m).
    r = await client.post(
        "/attendance/check-in", json=branch_position(accuracy_m=60), headers=auth(there)
    )
    assert_error(r, 422, "ATTENDANCE_LOCATION_INACCURATE")
    assert r.json()["error"]["details"]["max"] == 50
    r = await client.post("/attendance/check-in", json=branch_position(), headers=auth(there))
    assert r.status_code == 200, r.text
    rec = r.json()["record"]
    assert (rec["status"], rec["scheduled_start"]) == ("present", at("08:00").isoformat())
    assert rec["workplace_id"] == str(branch.id)
    # The branch's check-in closes at 08:20 (start + 20).
    late = await make_user(Role.SUPERVISOR, workplace_id=branch.id)
    clock(at("08:20"))
    r = await client.post("/attendance/check-in", json=branch_position(), headers=auth(late))
    assert_error(r, 409, "ATTENDANCE_CHECKIN_CLOSED")
    # Its check-out window: 12:00–12:30.
    clock(at("12:31"))
    r = await client.post("/attendance/check-out", json=branch_position(), headers=auth(there))
    assert_error(r, 409, "ATTENDANCE_CHECKOUT_CLOSED")
    user = await session.get(User, there.id)
    assert user is not None
