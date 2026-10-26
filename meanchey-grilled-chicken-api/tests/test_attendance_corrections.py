"""Attendance corrections (reason required, late recalculated from the snapshot, scope, audit)
and the day view (KPIs per shift and per workplace, one row per employee in scope, workplace
filter)."""

from sqlalchemy import select

from app.attendance import scheduler
from app.models import AuditLog, Role
from tests.conftest import assert_error, at, auth, branch_position, make_workplace, position


async def _check_in(client, clock, user, hm, metres=20):
    clock(hm)
    r = await client.post(
        "/attendance/check-in", json=position(metres_north=metres), headers=auth(user)
    )
    assert r.status_code == 200, r.text
    return r.json()["record"]


async def test_fix_a_record(client, session, clock, workplace, make_user) -> None:
    gm = await make_user(Role.GENERAL_MANAGER)
    staff = await make_user(Role.STAFF)
    rec = await _check_in(client, clock, staff, "07:20")
    assert rec["late_minutes"] == 20
    clock("09:00")

    body = {"status": "present", "check_in_time": "06:58", "reason": "Phone had no GPS"}
    r = await client.patch(f"/attendance/records/{rec['id']}", json=body, headers=auth(gm))
    assert r.status_code == 200, r.text
    fixed = r.json()
    assert (fixed["status"], fixed["late_minutes"]) == ("present", 0)
    assert fixed["check_in_at"].startswith("2026-10-13T06:58:00+07:00")
    assert fixed["corrected"] is True
    assert fixed["correction_reason"] == "Phone had no GPS"
    assert fixed["corrected_by"]["id"] == str(gm.id)
    assert fixed["source"] == "mini_app"
    # The location measured at check-in is kept.
    assert fixed["check_in_distance_m"] == rec["check_in_distance_m"]

    # "present" with a late time becomes late (late follows the time, from the snapshot).
    body = {"status": "present", "check_in_time": "07:31", "reason": "Arrived later"}
    fixed = (
        await client.patch(f"/attendance/records/{rec['id']}", json=body, headers=auth(gm))
    ).json()
    assert (fixed["status"], fixed["late_minutes"]) == ("late", 31)

    # Check-out and forgot.
    body = {
        "status": "late",
        "check_in_time": "07:31",
        "check_out_time": "12:05",
        "reason": "Left at 12:05",
    }
    fixed = (
        await client.patch(f"/attendance/records/{rec['id']}", json=body, headers=auth(gm))
    ).json()
    assert fixed["checkout_status"] == "checked_out"
    assert fixed["check_out_at"].startswith("2026-10-13T12:05:00+07:00")
    body = {
        "status": "late",
        "check_in_time": "07:31",
        "checkout_status": "forgot_checkout",
        "reason": "Forgot",
    }
    fixed = (
        await client.patch(f"/attendance/records/{rec['id']}", json=body, headers=auth(gm))
    ).json()
    assert (fixed["checkout_status"], fixed["check_out_at"]) == ("forgot_checkout", None)

    # Absent clears everything.
    body = {"status": "absent", "reason": "Wasn't here"}
    fixed = (
        await client.patch(f"/attendance/records/{rec['id']}", json=body, headers=auth(gm))
    ).json()
    assert (fixed["status"], fixed["check_in_at"], fixed["checkout_status"]) == (
        "absent",
        None,
        None,
    )
    assert fixed["check_in_distance_m"] is None

    entries = list(
        await session.scalars(
            select(AuditLog).where(AuditLog.action == "attendance.correct").order_by(AuditLog.id)
        )
    )
    assert len(entries) == 5
    first = entries[0]
    assert first.actor_id == gm.id and first.target_user_id == staff.id
    assert first.entity_type == "attendance_record"
    assert first.details["before"]["late_minutes"] == 20
    assert first.details["after"]["late_minutes"] == 0
    assert first.details["reason"] == "Phone had no GPS"


async def test_validation(client, clock, workplace, make_user) -> None:
    gm = await make_user(Role.GENERAL_MANAGER)
    staff = await make_user(Role.STAFF)
    rec = await _check_in(client, clock, staff, "07:00")
    url = f"/attendance/records/{rec['id']}"
    for body, field in [
        ({"status": "present", "check_in_time": "07:00", "reason": "  "}, "reason"),
        ({"status": "present", "check_in_time": "07:00"}, "reason"),
        ({"status": "present", "reason": "x"}, "check_in_time"),
        ({"status": "present", "check_in_time": "7:00", "reason": "x"}, "check_in_time"),
        (
            {
                "status": "present",
                "check_in_time": "07:00",
                "check_out_time": "06:00",
                "reason": "x",
            },
            "check_out_time",
        ),
        (
            {
                "status": "present",
                "check_in_time": "07:00",
                "checkout_status": "checked_out",
                "reason": "x",
            },
            "check_out_time",
        ),
    ]:
        r = await client.patch(url, json=body, headers=auth(gm))
        assert_error(r, 422, "VALIDATION_ERROR")
        assert any(field in f["loc"] for f in r.json()["error"]["details"]["fields"]), r.text
    r = await client.patch(
        "/attendance/records/00000000-0000-0000-0000-000000000000",
        json={"status": "absent", "reason": "x"},
        headers=auth(gm),
    )
    assert_error(r, 404, "ATTENDANCE_RECORD_NOT_FOUND")


async def test_add_a_missing_record(client, session, clock, workplace, make_user) -> None:
    gm = await make_user(Role.GENERAL_MANAGER)
    staff = await make_user(Role.STAFF)
    clock("16:30")
    body = {
        "user_id": str(staff.id),
        "work_date": "2026-10-13",
        "shift_code": "afternoon",
        "status": "present",
        "check_in_time": "13:10",
        "check_out_time": "15:05",
        "reason": "Checked in on paper",
    }
    r = await client.post("/attendance/records", json=body, headers=auth(gm))
    assert r.status_code == 201, r.text
    rec = r.json()
    assert (rec["source"], rec["status"], rec["late_minutes"]) == ("correction", "late", 10)
    assert rec["scheduled_start"].startswith("2026-10-13T13:00:00+07:00")
    assert rec["checkout_status"] == "checked_out"
    entry = await session.scalar(select(AuditLog).where(AuditLog.action == "attendance.correct"))
    assert entry.details["created"] is True and entry.details["before"] is None

    r = await client.post("/attendance/records", json=body, headers=auth(gm))
    assert_error(r, 409, "ATTENDANCE_RECORD_EXISTS")
    future = {**body, "work_date": "2026-10-14"}
    assert_error(
        await client.post("/attendance/records", json=future, headers=auth(gm)),
        422,
        "VALIDATION_ERROR",
    )


async def test_scope(client, clock, workplace, make_user, superadmin) -> None:
    gm = await make_user(Role.GENERAL_MANAGER)
    sup = await make_user(Role.SUPERVISOR, perms=["attendance.view", "attendance.correct"])
    other_sup = await make_user(Role.SUPERVISOR)
    staff = await make_user(Role.STAFF)
    sup_rec = await _check_in(client, clock, other_sup, "07:00")
    staff_rec = await _check_in(client, clock, staff, "07:05")
    body = {"status": "present", "check_in_time": "07:00", "reason": "Fix"}

    # A supervisor fixes staff, not another supervisor.
    r = await client.patch(f"/attendance/records/{staff_rec['id']}", json=body, headers=auth(sup))
    assert r.status_code == 200, r.text
    r = await client.patch(f"/attendance/records/{sup_rec['id']}", json=body, headers=auth(sup))
    assert_error(r, 403, "FORBIDDEN_SCOPE")
    # The GM and the superadmin fix supervisors.
    for actor in (gm, superadmin):
        r = await client.patch(
            f"/attendance/records/{sup_rec['id']}", json=body, headers=auth(actor)
        )
        assert r.status_code == 200, r.text
    # Nobody adds a record for a GM (not tracked) or for themselves.
    add = {
        "work_date": "2026-10-13",
        "shift_code": "morning",
        "status": "absent",
        "reason": "x",
    }
    r = await client.post(
        "/attendance/records", json={**add, "user_id": str(gm.id)}, headers=auth(superadmin)
    )
    assert_error(r, 422, "ATTENDANCE_NOT_REQUIRED")
    r = await client.post(
        "/attendance/records", json={**add, "user_id": str(sup.id)}, headers=auth(sup)
    )
    assert_error(r, 403, "FORBIDDEN_SCOPE")
    # The superadmin is never found.
    r = await client.post(
        "/attendance/records", json={**add, "user_id": str(superadmin.id)}, headers=auth(gm)
    )
    assert_error(r, 404, "USER_NOT_FOUND")
    # Without the permission.
    staff2 = await make_user(Role.STAFF)
    r = await client.patch(
        f"/attendance/records/{staff_rec['id']}", json=body, headers=auth(staff2)
    )
    assert_error(r, 403, "MISSING_PERMISSION")


async def test_day_view(client, session, clock, workplace, make_user) -> None:
    gm = await make_user(Role.GENERAL_MANAGER)
    sup = await make_user(Role.SUPERVISOR, perms=["attendance.view"])
    on_time = await make_user(Role.STAFF)
    late = await make_user(Role.STAFF)
    absent = await make_user(Role.STAFF)
    for u in (sup, on_time, late, absent):
        u.created_at = at("05:00", "2026-10-10")
    await session.commit()
    await _check_in(client, clock, on_time, "06:50")
    await _check_in(client, clock, late, "07:15")
    await _check_in(client, clock, sup, "06:59")
    await scheduler.run_tick(at("07:45"))
    clock("12:05")
    await client.post("/attendance/check-out", json=position(), headers=auth(on_time))
    await scheduler.run_tick(at("13:00"))  # late forgot to check out
    clock("13:10")

    day = (await client.get("/attendance/day", headers=auth(gm))).json()
    assert day["date"] == "2026-10-13"
    morning, afternoon = day["shifts"]
    assert morning["kpis"] == {
        "expected": 4,
        "present": 2,
        "late": 1,
        "absent": 1,
        "not_yet": 0,
        "no_record": 0,
        "checked_out": 1,
        "forgot_checkout": 2,  # late + the supervisor
    }
    assert afternoon["kpis"]["not_yet"] == 4
    assert afternoon["phase"] == "check_in_open"
    rows = {r["user"]["id"]: r for r in day["rows"]}
    assert set(rows) == {str(u.id) for u in (sup, on_time, late, absent)}
    assert day["rows"][0]["role"] == "supervisor"  # supervisors first
    cell = rows[str(late.id)]["shifts"]["morning"]
    assert cell["state"] == "recorded"
    assert (cell["record"]["status"], cell["record"]["late_minutes"]) == ("late", 15)
    cell = rows[str(absent.id)]["shifts"]["afternoon"]
    assert (cell["state"], cell["record"], cell["start"]) == ("not_yet", None, None)

    # A supervisor sees staff only.
    day = (await client.get("/attendance/day", headers=auth(sup))).json()
    assert {r["role"] for r in day["rows"]} == {"staff"}
    assert day["shifts"][0]["kpis"]["expected"] == 3

    # Another date: nobody yet has records there; past cutoffs mean no_record.
    day = (await client.get("/attendance/day?date=2026-10-12", headers=auth(gm))).json()
    assert day["shifts"][0]["kpis"]["no_record"] == 4
    assert all(c["record"] is None for r in day["rows"] for c in r["shifts"].values())
    # Staff without the permission.
    assert_error(
        await client.get("/attendance/day", headers=auth(on_time)), 403, "MISSING_PERMISSION"
    )


async def test_day_view_per_workplace(client, session, clock, workplace, make_user) -> None:
    branch = await make_workplace(session)
    gm = await make_user(Role.GENERAL_MANAGER)
    here = await make_user(Role.STAFF, workplace_id=workplace.id)
    there = await make_user(Role.STAFF, workplace_id=branch.id)
    for u in (here, there):
        u.created_at = at("05:00", "2026-10-10")
    await session.commit()
    clock("07:50")
    r = await client.post("/attendance/check-in", json=branch_position(), headers=auth(there))
    assert r.status_code == 200, r.text

    day = (await client.get("/attendance/day", headers=auth(gm))).json()
    assert {w["name"] for w in day["workplace_options"]} == {"Mean Chey", "Branch 2"}
    by_name = {w["name"]: w for w in day["workplaces"]}
    # Each workplace with its own times and KPIs: the default's check-in closed at 07:45.
    default_morning = by_name["Mean Chey"]["shifts"][0]
    assert default_morning["start"] == at("07:00").isoformat()
    assert default_morning["kpis"]["no_record"] == 1
    branch_morning = by_name["Branch 2"]["shifts"][0]
    assert branch_morning["start"] == at("08:00").isoformat()
    assert (branch_morning["kpis"]["present"], branch_morning["phase"]) == (1, "check_in_open")
    assert day["shifts"][0]["kpis"]["expected"] == 2
    rows = {r["user"]["id"]: r for r in day["rows"]}
    assert rows[str(there.id)]["workplace"] == {"id": str(branch.id), "name": "Branch 2"}

    # Filtered: only that workplace's employees, its times as the headline.
    day = (await client.get(f"/attendance/day?workplace_id={branch.id}", headers=auth(gm))).json()
    assert [r["user"]["id"] for r in day["rows"]] == [str(there.id)]
    assert day["workplace_id"] == str(branch.id)
    assert day["shifts"][0]["start"] == at("08:00").isoformat()
    assert [w["name"] for w in day["workplaces"]] == ["Branch 2"]
    import uuid

    assert_error(
        await client.get(f"/attendance/day?workplace_id={uuid.uuid4()}", headers=auth(gm)),
        404,
        "ATTENDANCE_WORKPLACE_NOT_FOUND",
    )
