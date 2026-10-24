"""Attendance scheduling: schedule versions (effective dates, replace, upcoming, later versions
follow), tracked weekdays and holidays as days off (check-in refused, next action, scheduler,
summaries, day view, calendar), scope (one, several, all workplaces, later ones), retroactive
effects (records removed except corrected ones; absents recreated), copying holidays, and access.

The test day 2026-10-13 is a Tuesday (ISO weekday 2)."""

from datetime import date

from sqlalchemy import select, update

from app.attendance import scheduler
from app.attendance.workplaces import version_on
from app.main import app
from app.models import (
    AttendanceRecord,
    AttendanceReminder,
    AttendanceScheduleVersion,
    AttendanceWorkplace,
    AuditLog,
    Role,
    User,
)
from tests.conftest import (
    SCHEDULE_SINCE,
    assert_error,
    at,
    auth,
    make_workplace,
    position,
)

EVERY_DAY = [1, 2, 3, 4, 5, 6, 7]
NO_TUESDAY = [1, 3, 4, 5, 6, 7]
SHIFTS = {
    "shifts": [
        {
            "code": "morning",
            "name_km": "វេនព្រឹក",
            "name_en": "Morning shift",
            "start_time": "07:00",
            "end_time": "12:00",
        },
        {
            "code": "afternoon",
            "name_km": "វេនរសៀល",
            "name_en": "Afternoon shift",
            "start_time": "13:00",
            "end_time": "15:00",
        },
    ],
    "open_before_min": 30,
    "absent_after_min": 45,
    "checkout_window_min": 59,
    "reminders_enabled": True,
    "count_early_checkin": True,
    "count_overtime": True,
}


def shifts_body(targets="all", **changes) -> dict:
    body = {**SHIFTS, "shifts": [dict(s) for s in SHIFTS["shifts"]], "workplace_ids": targets}
    for key, value in changes.items():
        if key in ("morning", "afternoon"):
            shift = next(s for s in body["shifts"] if s["code"] == key)
            shift["start_time"], shift["end_time"] = value
        else:
            body[key] = value
    return body


def holiday_body(start="2026-10-13", end=None, scope="all", workplace_ids=None, **extra) -> dict:
    body = {
        "name_km": "ភ្ជុំបិណ្ឌ",
        "name_en": "Pchum Ben",
        "start_date": start,
        "end_date": end or start,
        "scope": scope,
        **extra,
    }
    if workplace_ids is not None:
        body["workplace_ids"] = [str(w) for w in workplace_ids]
    return body


async def _versions(session, workplace) -> list[AttendanceScheduleVersion]:
    return list(
        await session.scalars(
            select(AttendanceScheduleVersion)
            .where(AttendanceScheduleVersion.workplace_id == workplace.id)
            .order_by(AttendanceScheduleVersion.effective_from)
            .execution_options(populate_existing=True)
        )
    )


async def _audit(session, action: str) -> list[AuditLog]:
    return list(
        await session.scalars(
            select(AuditLog).where(AuditLog.action == action).order_by(AuditLog.id)
        )
    )


async def _backdate(session, *users, when="2026-10-01 05:00") -> None:
    day, hm = when.split()
    await session.execute(
        update(User).where(User.id.in_([u.id for u in users])).values(created_at=at(hm, day))
    )
    await session.commit()


async def _records(session) -> list[AttendanceRecord]:
    return list(
        await session.scalars(
            select(AttendanceRecord)
            .order_by(AttendanceRecord.work_date, AttendanceRecord.scheduled_start)
            .execution_options(populate_existing=True)
        )
    )


async def _tick(now):
    return await scheduler.run_tick(now, app.state.telegram)


# --- Versions ------------------------------------------------------------------------------------


def test_version_on_picks_the_latest_started() -> None:
    v = [
        AttendanceScheduleVersion(effective_from=date(2026, 1, 1)),
        AttendanceScheduleVersion(effective_from=date(2026, 10, 20)),
    ]
    assert version_on(v, date(2026, 10, 19)) is v[0]
    assert version_on(v, date(2026, 10, 20)) is v[1]
    assert version_on(v, date(2027, 1, 1)) is v[1]
    # Before the first version: the first.
    assert version_on(v, date(2025, 5, 1)) is v[0]
    assert version_on([], date(2026, 1, 1)) is None


async def test_weekdays_from_today_and_future(client, session, clock, superadmin, workplace):
    h = auth(superadmin)
    # Today (the default): a new version from 2026-10-13.
    r = await client.put(
        "/attendance/scheduling/weekdays",
        json={"workplace_ids": "all", "weekdays": [5, 1, 2, 3, 4]},
        headers=h,
    )
    assert r.status_code == 200, r.text
    (wp,) = r.json()["scheduling"]["workplaces"]
    assert wp["current"]["weekdays"] == [1, 2, 3, 4, 5]
    assert wp["current"]["effective_from"] == "2026-10-13"
    assert [v.effective_from for v in await _versions(session, workplace)] == [
        SCHEDULE_SINCE,
        date(2026, 10, 13),
    ]
    # The same date again: replaced, no new version.
    r = await client.put(
        "/attendance/scheduling/weekdays",
        json={"workplace_ids": [str(workplace.id)], "weekdays": EVERY_DAY},
        headers=h,
    )
    assert r.json()["scheduling"]["workplaces"][0]["current"]["weekdays"] == EVERY_DAY
    assert len(await _versions(session, workplace)) == 2
    # Past dates are refused.
    r = await client.put(
        "/attendance/scheduling/weekdays",
        json={"workplace_ids": "all", "weekdays": [1], "effective_from": "2026-10-12"},
        headers=h,
    )
    assert_error(r, 422, "VALIDATION_ERROR")
    assert r.json()["error"]["details"]["fields"][0]["loc"] == ["body", "effective_from"]
    for bad in ([], [0], [8]):
        r = await client.put(
            "/attendance/scheduling/weekdays",
            json={"workplace_ids": "all", "weekdays": bad},
            headers=h,
        )
        assert_error(r, 422, "VALIDATION_ERROR")
    # A future date: upcoming, today unchanged.
    r = await client.put(
        "/attendance/scheduling/weekdays",
        json={"workplace_ids": "all", "weekdays": [1, 2, 3], "effective_from": "2026-11-01"},
        headers=h,
    )
    (wp,) = r.json()["scheduling"]["workplaces"]
    assert wp["current"]["weekdays"] == EVERY_DAY
    assert [(v["effective_from"], v["weekdays"]) for v in wp["upcoming"]] == [
        ("2026-11-01", [1, 2, 3])
    ]
    entries = await _audit(session, "attendance.weekdays_update")
    assert len(entries) == 3
    assert entries[-1].details["effective_from"] == "2026-11-01"
    assert entries[-1].details["changes"]["Mean Chey"]["weekdays"] == [EVERY_DAY, [1, 2, 3]]


async def test_a_change_holds_from_its_date_on(client, session, clock, superadmin, workplace):
    """An upcoming shift change, then a weekday change from an earlier date: the later version
    gets the weekdays too (else it would bring the old ones back)."""
    h = auth(superadmin)
    r = await client.put(
        "/attendance/scheduling/shifts",
        json=shifts_body(morning=("07:30", "12:00"), effective_from="2026-11-01"),
        headers=h,
    )
    assert r.status_code == 200, r.text
    r = await client.put(
        "/attendance/scheduling/weekdays",
        json={"workplace_ids": "all", "weekdays": [1, 2, 3, 4, 5], "effective_from": "2026-10-20"},
        headers=h,
    )
    assert r.status_code == 200, r.text
    versions = await _versions(session, workplace)
    assert [(v.effective_from, v.weekdays, v.shifts[0]["start_time"]) for v in versions] == [
        (SCHEDULE_SINCE, EVERY_DAY, "07:00"),
        (date(2026, 10, 20), [1, 2, 3, 4, 5], "07:00"),
        (date(2026, 11, 1), [1, 2, 3, 4, 5], "07:30"),
    ]
    (entry,) = await _audit(session, "attendance.weekdays_update")
    assert entry.details["changes"]["Mean Chey"]["later_versions"] == 1


async def test_delete_upcoming_versions_only(client, session, clock, superadmin, workplace):
    h = auth(superadmin)
    r = await client.put(
        "/attendance/scheduling/weekdays",
        json={"workplace_ids": "all", "weekdays": [1, 2], "effective_from": "2026-12-01"},
        headers=h,
    )
    upcoming = r.json()["scheduling"]["workplaces"][0]["upcoming"][0]["id"]
    current = r.json()["scheduling"]["workplaces"][0]["current"]["id"]
    assert_error(
        await client.delete(f"/attendance/scheduling/versions/{current}", headers=h),
        409,
        "ATTENDANCE_SCHEDULE_VERSION_IN_EFFECT",
    )
    r = await client.delete(f"/attendance/scheduling/versions/{upcoming}", headers=h)
    assert r.status_code == 204, r.text
    assert len(await _versions(session, workplace)) == 1
    assert_error(
        await client.delete(f"/attendance/scheduling/versions/{upcoming}", headers=h),
        404,
        "ATTENDANCE_SCHEDULE_VERSION_NOT_FOUND",
    )
    assert len(await _audit(session, "attendance.schedule_version_delete")) == 1


async def test_shifts_put(client, session, clock, superadmin, make_user, workplace) -> None:
    staff = await make_user(Role.STAFF, workplace_id=workplace.id)
    clock("07:10")
    await client.post("/attendance/check-in", json=position(), headers=auth(staff))
    body = shifts_body(morning=("07:30", "11:30"), open_before_min=20)
    body["shifts"][0]["name_en"] = "Early shift"
    r = await client.put("/attendance/scheduling/shifts", json=body, headers=auth(superadmin))
    assert r.status_code == 200, r.text
    current = r.json()["scheduling"]["workplaces"][0]["current"]
    assert current["open_before_min"] == 20
    assert current["shifts"][0]["name_en"] == "Early shift"
    assert current["shifts"][0]["windows"]["check_in_opens"] == "07:10"
    (entry,) = await _audit(session, "attendance.schedule_update")
    assert entry.details["all_workplaces"] is True
    changes = entry.details["changes"]["Mean Chey"]
    assert changes["open_before_min"] == [30, 20]
    assert changes["shifts"][1]["morning"] == "07:30–11:30"
    # The record keeps its snapshot.
    (record,) = await _records(session)
    assert record.scheduled_start == at("07:00") and record.late_minutes == 10
    # The workplace page shows the new schedule (read-only).
    out = (
        await client.get(f"/attendance/workplaces/{workplace.id}", headers=auth(superadmin))
    ).json()
    assert out["schedule"]["shifts"][0]["start_time"] == "07:30"

    for bad in (
        shifts_body(morning=("12:00", "08:00")),
        shifts_body(morning=("07:00", "14:00")),
        shifts_body(morning=("00:10", "05:00")),
        shifts_body(afternoon=("13:00", "23:30")),
        shifts_body(morning=("7:00", "12:00")),
        shifts_body(absent_after_min=200),
        shifts_body(open_before_min=0),
        shifts_body(open_before_min=121),
        shifts_body(checkout_window_min=181),
        # The accuracy rule is gone: sending it is an unknown field.
        {**shifts_body(), "max_accuracy_m": 100},
        shifts_body(targets=[]),
        {**shifts_body(), "shifts": SHIFTS["shifts"][:1]},
    ):
        assert_error(
            await client.put("/attendance/scheduling/shifts", json=bad, headers=auth(superadmin)),
            422,
            "VALIDATION_ERROR",
        )
    # An identical write changes nothing and writes no audit entry.
    await client.put("/attendance/scheduling/shifts", json=body, headers=auth(superadmin))
    assert len(await _audit(session, "attendance.schedule_update")) == 1


async def test_targets_one_several_all(client, session, clock, superadmin, workplace) -> None:
    branch = await make_workplace(session)
    third = await make_workplace(session, "Third", metres_north=9000)
    old = await make_workplace(session, "Old", metres_north=12000)
    old.is_active = False
    await session.commit()
    h = auth(superadmin)
    r = await client.put(
        "/attendance/scheduling/weekdays",
        json={"workplace_ids": [str(branch.id), str(third.id)], "weekdays": [1, 2, 3, 4, 5]},
        headers=h,
    )
    assert r.status_code == 200, r.text
    assert [w["name"] for w in r.json()["scheduling"]["workplaces"]] == ["Branch 2", "Third"]
    assert len(await _versions(session, workplace)) == 1
    # All three shown: the weekdays differ, shifts too (the branches have their own times).
    out = (await client.get("/attendance/scheduling", headers=h)).json()
    assert [w["name"] for w in out["workplaces"]] == ["Mean Chey", "Branch 2", "Third"]
    assert out["differs"] == {"weekdays": True, "shifts": True}
    one = (
        await client.get(
            f"/attendance/scheduling?workplace_ids={branch.id}&workplace_ids={third.id}",
            headers=h,
        )
    ).json()
    assert one["differs"] == {"weekdays": False, "shifts": False}
    assert len(one["workplace_options"]) == 3
    # "all": every active workplace in one transaction (the archived one is left alone).
    r = await client.put("/attendance/scheduling/shifts", json=shifts_body(), headers=h)
    assert r.status_code == 200, r.text
    out = (await client.get("/attendance/scheduling", headers=h)).json()
    assert out["differs"]["shifts"] is False
    assert (await _versions(session, old))[-1].shifts[0]["start_time"] == "08:00"
    # Unknown or archived targets.
    assert_error(
        await client.put(
            "/attendance/scheduling/weekdays",
            json={"workplace_ids": [str(old.id)], "weekdays": [1]},
            headers=h,
        ),
        409,
        "WORKPLACE_ARCHIVED",
    )
    assert_error(
        await client.get(f"/attendance/scheduling?workplace_ids={superadmin.id}", headers=h),
        404,
        "ATTENDANCE_WORKPLACE_NOT_FOUND",
    )


# --- Days off ------------------------------------------------------------------------------------


async def _no_tuesdays(session, workplace) -> None:
    for v in await _versions(session, workplace):
        v.weekdays = NO_TUESDAY
    await session.commit()


async def test_weekday_off(client, session, clock, workplace, make_user, telegram_bot) -> None:
    staff = await make_user(Role.STAFF, telegram_user_id=9001)
    await _backdate(session, staff)
    await _no_tuesdays(session, workplace)
    clock("06:45")
    r = await client.post("/attendance/check-in", json=position(), headers=auth(staff))
    assert_error(r, 409, "ATTENDANCE_DAY_OFF")
    details = r.json()["error"]["details"]
    assert details["reason"] == "weekday" and details["holidays"] == []
    assert details["next_opens_at"] == at("06:30", "2026-10-14").isoformat()
    assert_error(
        await client.post("/attendance/check-out", json=position(), headers=auth(staff)),
        409,
        "ATTENDANCE_DAY_OFF",
    )
    me = (await client.get("/attendance/me/today", headers=auth(staff))).json()
    assert me["day_off"] == {"reason": "weekday", "holidays": []}
    assert me["shifts"] == []
    assert me["next_action"]["action"] == "none"
    assert me["next_action"]["next_opens_at"] == at("06:30", "2026-10-14").isoformat()
    # Nobody is reminded or marked absent; Wednesday is tracked again.
    for t in ("06:30", "07:45", "12:00", "13:45", "16:00"):
        result = await _tick(at(t))
        assert (result.absent, result.reminders) == (0, [])
    assert telegram_bot.calls("SendMessage") == []
    assert (await _tick(at("07:45", "2026-10-14"))).absent == 1


async def test_holiday_day_off(client, session, clock, superadmin, workplace, make_user) -> None:
    staff = await make_user(Role.STAFF)
    await _backdate(session, staff)
    clock(at("08:00", "2026-10-01"))
    r = await client.post(
        "/attendance/holidays",
        json=holiday_body("2026-10-12", "2026-10-14", note="  Three days  "),
        headers=auth(superadmin),
    )
    assert r.status_code == 201, r.text
    holiday = r.json()["holiday"]
    assert (holiday["days"], holiday["scope"], holiday["note"]) == (3, "all", "Three days")
    clock("06:45")
    r = await client.post("/attendance/check-in", json=position(), headers=auth(staff))
    assert_error(r, 409, "ATTENDANCE_DAY_OFF")
    details = r.json()["error"]["details"]
    assert details["reason"] == "holiday"
    assert details["holidays"] == [{"name_km": "ភ្ជុំបិណ្ឌ", "name_en": "Pchum Ben"}]
    assert details["next_opens_at"] == at("06:30", "2026-10-15").isoformat()
    me = (await client.get("/attendance/me/today", headers=auth(staff))).json()
    assert me["day_off"]["reason"] == "holiday"
    assert me["day_off"]["holidays"][0]["name_en"] == "Pchum Ben"
    assert (await _tick(at("16:00"))).absent == 0


async def test_holiday_scope(client, session, clock, superadmin, workplace, make_user) -> None:
    branch = await make_workplace(session)
    here = await make_user(Role.STAFF, workplace_id=workplace.id)
    there = await make_user(Role.STAFF, workplace_id=branch.id)
    await _backdate(session, here, there)
    clock(at("08:00", "2026-10-01"))
    h = auth(superadmin)
    r = await client.post(
        "/attendance/holidays",
        json=holiday_body("2026-10-13", scope="selected", workplace_ids=[branch.id]),
        headers=h,
    )
    assert r.status_code == 201, r.text
    assert [w["name"] for w in r.json()["holiday"]["workplaces"]] == ["Branch 2"]
    for bad in (
        holiday_body(scope="selected"),
        holiday_body(scope="selected", workplace_ids=[]),
        holiday_body("2026-10-13", "2026-10-12"),
        holiday_body("2026-10-01", "2026-11-01"),
        {**holiday_body(), "name_en": "  "},
    ):
        assert_error(
            await client.post("/attendance/holidays", json=bad, headers=h), 422, "VALIDATION_ERROR"
        )
    clock("16:00")
    result = await _tick(at("16:00"))
    assert result.absent == 2  # the default workplace's employee, morning and afternoon
    assert {r.user_id for r in await _records(session)} == {here.id}
    # An "all" holiday also covers a workplace created later.
    clock(at("08:00", "2026-10-01"))
    await client.post(
        "/attendance/holidays", json=holiday_body("2026-10-20", scope="all"), headers=h
    )
    later = await make_workplace(session, "Later", metres_north=9000)
    cal = (
        await client.get(
            f"/attendance/calendar?year=2026&month=10&workplace_ids={later.id}", headers=h
        )
    ).json()
    day20 = next(d for d in cal["days"] if d["date"] == "2026-10-20")
    assert day20["status"] == "off" and day20["day_off"]["reason"] == "holiday"
    # Several workplaces: the 13th is off at the branch only.
    cal = (await client.get("/attendance/calendar?year=2026&month=10", headers=h)).json()
    day13 = next(d for d in cal["days"] if d["date"] == "2026-10-13")
    assert day13["status"] == "mixed"
    assert [d["day_off"] is not None for d in day13["workplaces"]] == [False, True, False]
    assert day13["holidays"][0]["name_en"] == "Pchum Ben"
    listed = (await client.get("/attendance/holidays?year=2026", headers=h)).json()
    assert [x["start_date"] for x in listed] == ["2026-10-13", "2026-10-20"]
    only = (
        await client.get(f"/attendance/holidays?year=2026&workplace_id={workplace.id}", headers=h)
    ).json()
    assert [x["start_date"] for x in only] == ["2026-10-20"]


async def test_calendar_weekdays(client, session, clock, superadmin, workplace) -> None:
    await _no_tuesdays(session, workplace)
    cal = (
        await client.get("/attendance/calendar?year=2026&month=10", headers=auth(superadmin))
    ).json()
    assert len(cal["days"]) == 31 and cal["today"] == "2026-10-13"
    by_date = {d["date"]: d for d in cal["days"]}
    assert by_date["2026-10-13"]["status"] == "off"
    assert by_date["2026-10-13"]["day_off"] == {"reason": "weekday", "holidays": []}
    assert by_date["2026-10-14"]["status"] == "tracked"
    assert by_date["2026-10-14"]["workplaces"] is None


async def test_summary_and_day_view_skip_days_off(
    client, session, clock, superadmin, workplace, make_user
) -> None:
    gm = await make_user(Role.GENERAL_MANAGER)
    staff = await make_user(Role.STAFF)
    await _backdate(session, staff, when="2026-10-11 05:00")
    # Absent on the 12th (two shifts); a corrected record on the 13th, then the 13th becomes a
    # holiday: the corrected record is kept but not counted.
    await _tick(at("16:00", "2026-10-12"))
    clock("16:00")
    r = await client.post(
        "/attendance/records",
        json={
            "user_id": str(staff.id),
            "work_date": "2026-10-13",
            "shift_code": "morning",
            "status": "present",
            "check_in_time": "07:00",
            "reason": "On paper",
        },
        headers=auth(gm),
    )
    assert r.status_code == 201, r.text
    await client.post("/attendance/holidays", json=holiday_body(), headers=auth(superadmin))
    out = (await client.get("/attendance/me/summary", headers=auth(staff))).json()
    assert out["kpis"]["absent"]["total_shifts"] == 2
    assert out["kpis"]["present"]["total_shifts"] == 0
    days = {d["date"]: d for d in out["days"]}
    assert days["2026-10-13"]["day_off"]["reason"] == "holiday"
    assert days["2026-10-13"]["shifts"][0]["status"] == "present"  # still listed
    assert days["2026-10-12"]["day_off"] is None
    day = (await client.get("/attendance/day?date=2026-10-13", headers=auth(gm))).json()
    assert day["day_off"]["reason"] == "holiday"
    (row,) = day["rows"]
    assert row["day_off"]["reason"] == "holiday"
    assert {k: v["state"] for k, v in row["shifts"].items()} == {
        "morning": "recorded",
        "afternoon": "day_off",
    }
    assert all(s["kpis"]["expected"] == 0 for s in day["shifts"])


# --- Retroactive effects -------------------------------------------------------------------------


async def test_holiday_today_removes_records_and_back(
    client, session, clock, superadmin, workplace, make_user
) -> None:
    gm = await make_user(Role.GENERAL_MANAGER)
    came = await make_user(Role.STAFF)
    missed = await make_user(Role.STAFF)
    fixed = await make_user(Role.STAFF)
    await _backdate(session, came, missed, fixed)
    clock("07:05")
    assert (
        await client.post("/attendance/check-in", json=position(), headers=auth(came))
    ).status_code == 200
    await _tick(at("07:45"))  # missed and fixed: absent
    records = {r.user_id: r for r in await _records(session)}
    r = await client.patch(
        f"/attendance/records/{records[fixed.id].id}",
        json={"status": "present", "check_in_time": "07:00", "reason": "Was there"},
        headers=auth(gm),
    )
    assert r.status_code == 200, r.text
    # Yesterday too (absent, and it stays: the holiday is today only).
    await _tick(at("16:00", "2026-10-12"))
    clock("09:00")
    r = await client.post("/attendance/holidays", json=holiday_body(), headers=auth(superadmin))
    assert r.status_code == 201, r.text
    assert r.json()["records_removed"] == 2
    left = await _records(session)
    assert {(x.user_id, str(x.work_date)) for x in left if str(x.work_date) == "2026-10-13"} == {
        (fixed.id, "2026-10-13")
    }
    assert len([x for x in left if str(x.work_date) == "2026-10-12"]) == 6
    (entry,) = await _audit(session, "attendance.records_removed_by_day_off")
    assert entry.details["count"] == 2 and entry.details["cause"] == "attendance.holiday_create"
    removed = {x["user_id"]: x for x in entry.details["records"]}
    assert removed[str(came.id)]["status"] == "late"
    assert removed[str(came.id)]["check_in_at"].startswith("2026-10-13T00:05:00")
    assert removed[str(missed.id)]["source"] == "auto"
    # Reminders and absents stop for today.
    assert (await _tick(at("13:45"))).absent == 0
    # Removing the holiday brings the passed cutoffs back: the morning's absents.
    holiday_id = r.json()["holiday"]["id"]
    r = await client.delete(f"/attendance/holidays/{holiday_id}", headers=auth(superadmin))
    assert r.status_code == 200, r.text
    assert r.json()["absents_recreated"] == 2  # came and missed (fixed has its record)
    today = [x for x in await _records(session) if str(x.work_date) == "2026-10-13"]
    assert sorted(x.status for x in today) == ["absent", "absent", "present"]
    assert len(await _audit(session, "attendance.holiday_delete")) == 1


async def test_shortening_a_holiday(client, session, clock, superadmin, workplace, make_user):
    staff = await make_user(Role.STAFF)
    await _backdate(session, staff)
    clock("09:00")
    r = await client.post(
        "/attendance/holidays",
        json=holiday_body("2026-10-10", "2026-10-13"),
        headers=auth(superadmin),
    )
    hid = r.json()["holiday"]["id"]
    assert await _records(session) == []
    r = await client.patch(
        f"/attendance/holidays/{hid}",
        json=holiday_body("2026-10-10", "2026-10-11"),
        headers=auth(superadmin),
    )
    assert r.status_code == 200, r.text
    # The 12th (both shifts) and the 13th's passed morning cutoff get absents back.
    assert r.json()["absents_recreated"] == 3
    (entry,) = await _audit(session, "attendance.holiday_update")
    assert entry.details["before"]["end_date"] == "2026-10-13"
    assert entry.details["after"]["end_date"] == "2026-10-11"


async def test_weekday_change_today_removes_and_restores(
    client, session, clock, superadmin, workplace, make_user
) -> None:
    staff = await make_user(Role.STAFF)
    await _backdate(session, staff)
    await _tick(at("07:45"))
    clock("08:00")
    h = auth(superadmin)
    r = await client.put(
        "/attendance/scheduling/weekdays",
        json={"workplace_ids": "all", "weekdays": NO_TUESDAY},
        headers=h,
    )
    assert r.json()["records_removed"] == 1
    assert await _records(session) == []
    r = await client.put(
        "/attendance/scheduling/weekdays",
        json={"workplace_ids": "all", "weekdays": EVERY_DAY},
        headers=h,
    )
    assert r.json()["absents_recreated"] == 1
    # From a future date: nothing happens to today.
    r = await client.put(
        "/attendance/scheduling/weekdays",
        json={"workplace_ids": "all", "weekdays": NO_TUESDAY, "effective_from": "2026-10-14"},
        headers=h,
    )
    assert r.json()["records_removed"] == 0 and len(await _records(session)) == 1


async def test_pending_reminders_skipped_on_a_day_off(
    client, session, clock, superadmin, workplace, make_user
) -> None:
    staff = await make_user(Role.STAFF, telegram_user_id=9100)
    await _backdate(session, staff)
    session.add(
        AttendanceReminder(
            user_id=staff.id,
            work_date=date(2026, 10, 13),
            shift_code="morning",
            kind="check_in",
            window_closes_at=at("07:45"),
        )
    )
    await session.commit()
    clock("06:31")
    await client.post("/attendance/holidays", json=holiday_body(), headers=auth(superadmin))
    result = await _tick(at("06:32"))
    assert result.skipped == 1 and result.reminders == []


# --- Copy from last year -------------------------------------------------------------------------


async def test_copy_holidays(client, session, clock, superadmin, workplace) -> None:
    branch = await make_workplace(session)
    h = auth(superadmin)
    clock(at("08:00", "2024-01-01"))
    for body in (
        holiday_body("2024-02-29", name_en="Leap", name_km="លោត"),
        holiday_body("2024-04-14", "2024-04-16", name_en="Khmer New Year", name_km="ចូលឆ្នាំ"),
        holiday_body(
            "2024-12-31",
            "2025-01-01",
            scope="selected",
            workplace_ids=[branch.id],
            name_en="New Year",
            name_km="ឆ្នាំថ្មី",
        ),
    ):
        assert (await client.post("/attendance/holidays", json=body, headers=h)).status_code == 201
    clock("08:00")
    # Already there in 2025 (same name and dates): skipped.
    r = await client.post(
        "/attendance/holidays",
        json=holiday_body("2025-04-14", "2025-04-16", name_en="Khmer New Year", name_km="x"),
        headers=h,
    )
    assert r.status_code == 201, r.text
    r = await client.post(
        "/attendance/holidays/copy", json={"from_year": 2024, "to_year": 2025}, headers=h
    )
    assert r.status_code == 201, r.text
    out = r.json()
    assert out["skipped"] == 1
    assert [(x["name_en"], x["start_date"], x["end_date"]) for x in out["created"]] == [
        ("Leap", "2025-02-28", "2025-02-28"),
        ("New Year", "2025-12-31", "2026-01-01"),
    ]
    assert out["created"][1]["scope"] == "selected"
    assert [w["name"] for w in out["created"][1]["workplaces"]] == ["Branch 2"]
    (entry,) = await _audit(session, "attendance.holiday_copy")
    assert entry.details["skipped"] == 1
    # Copying again creates nothing.
    r = await client.post(
        "/attendance/holidays/copy", json={"from_year": 2024, "to_year": 2025}, headers=h
    )
    assert (r.json()["created"], r.json()["skipped"]) == ([], 3)
    assert_error(
        await client.post(
            "/attendance/holidays/copy", json={"from_year": 2025, "to_year": 2025}, headers=h
        ),
        422,
        "VALIDATION_ERROR",
    )


# --- Access --------------------------------------------------------------------------------------


async def test_access(client, session, clock, superadmin, make_user, workplace) -> None:
    gm = await make_user(Role.GENERAL_MANAGER)
    sup = await make_user(Role.SUPERVISOR)
    writes = (
        ("PUT", "/attendance/scheduling/weekdays", {"workplace_ids": "all", "weekdays": [1]}),
        ("PUT", "/attendance/scheduling/shifts", shifts_body()),
        ("POST", "/attendance/holidays", holiday_body("2026-12-25")),
        ("POST", "/attendance/holidays/copy", {"from_year": 2025, "to_year": 2026}),
    )
    # GM: off by default; viewing comes with attendance.view.
    for method, path, body in writes:
        assert_error(
            await client.request(method, path, json=body, headers=auth(gm)),
            403,
            "MISSING_PERMISSION",
        )
    for path in (
        "/attendance/scheduling",
        "/attendance/calendar?year=2026&month=10",
        "/attendance/holidays",
    ):
        assert (await client.get(path, headers=auth(gm))).status_code == 200
        assert_error(await client.get(path, headers=auth(sup)), 403, "MISSING_PERMISSION")
    # The GM can't see the feature (grantor_must_hold) and so can't give it.
    features = (await client.get(f"/users/{sup.id}/features", headers=auth(gm))).json()
    codes = {f["code"] for m in features["menus"] for f in m["features"]}
    assert "attendance_scheduling" not in codes
    r = await client.put(
        f"/users/{sup.id}/features/attendance_scheduling", json={"level": "full"}, headers=auth(gm)
    )
    assert r.json()["error"]["code"] == "FEATURE_NOT_FOUND"
    # The superadmin turns it on for the GM.
    r = await client.put(
        f"/users/{gm.id}/features/attendance_scheduling",
        json={"level": "full"},
        headers=auth(superadmin),
    )
    assert r.status_code == 200, r.text
    for method, path, body in writes:
        r = await client.request(method, path, json=body, headers=auth(gm))
        assert r.status_code in (200, 201), r.text
    # Now the GM can give it to a supervisor, who then manages scheduling.
    r = await client.put(
        f"/users/{sup.id}/features/attendance_scheduling", json={"level": "full"}, headers=auth(gm)
    )
    assert r.status_code == 200, r.text
    assert (await client.get("/attendance/scheduling", headers=auth(sup))).status_code == 200
    r = await client.post(
        "/attendance/holidays", json=holiday_body("2026-12-26"), headers=auth(sup)
    )
    assert r.status_code == 201, r.text
    # Staff never.
    staff = await make_user(Role.STAFF)
    assert_error(
        await client.get("/attendance/scheduling", headers=auth(staff)), 403, "MISSING_PERMISSION"
    )


async def test_new_workplace_copies_the_current_version(
    client, session, clock, superadmin, workplace
) -> None:
    h = auth(superadmin)
    await client.put(
        "/attendance/scheduling/weekdays",
        json={"workplace_ids": "all", "weekdays": [1, 2, 3, 4, 5]},
        headers=h,
    )
    # An upcoming change isn't copied (only the current version).
    await client.put(
        "/attendance/scheduling/weekdays",
        json={"workplace_ids": "all", "weekdays": [1], "effective_from": "2026-12-01"},
        headers=h,
    )
    r = await client.post("/attendance/workplaces", json={"name": "New"}, headers=h)
    w = await session.get(AttendanceWorkplace, r.json()["id"])
    versions = await _versions(session, w)
    assert [(v.effective_from, v.weekdays) for v in versions] == [
        (date(2026, 10, 13), [1, 2, 3, 4, 5])
    ]
