"""Employees' own schedules and holiday work exceptions: the resolver (inherit vs override per
field, workplace changes, morning / afternoon only, custom times and windows, weekdays,
holidays and exceptions, tracking first), validation and conflicts, effective dates (today:
unopened shifts only), bulk writes, reset, scope, the scheduler, `me/today`, the day view,
summaries, the calendar, notifications and audit.

The test day 2026-10-13 is a Tuesday; 2026-10-18 is a Sunday."""

from sqlalchemy import select, update

from app.attendance import overrides as ovr
from app.attendance import scheduler
from app.bot.notify import message_for
from app.main import app
from app.models import (
    AttendanceEmployeeOverride,
    AttendanceHolidayException,
    AttendanceRecord,
    AttendanceReminder,
    AuditLog,
    Language,
    Notification,
    Role,
    User,
)
from app.permissions.registry import DEFAULT_PERMISSIONS
from tests.conftest import assert_error, at, auth, position

TUE, WED, THU, SUN = "2026-10-13", "2026-10-14", "2026-10-15", "2026-10-18"
MON_SAT = [1, 2, 3, 4, 5, 6]
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


def shifts_body(morning=("07:00", "12:00"), afternoon=("13:00", "15:00"), **extra) -> dict:
    body = {**SHIFTS, "workplace_ids": "all", **extra}
    body["shifts"] = [
        {**SHIFTS["shifts"][0], "start_time": morning[0], "end_time": morning[1]},
        {**SHIFTS["shifts"][1], "start_time": afternoon[0], "end_time": afternoon[1]},
    ]
    return body


def morning_only(start="07:30", end="12:00", **extra) -> dict:
    return {
        "weekdays": MON_SAT,
        "shift_codes": ["morning"],
        "shift_times": {"morning": {"start_time": start, "end_time": end}},
        **extra,
    }


async def scheduler_gm(make_user) -> User:
    perms = [*DEFAULT_PERMISSIONS[Role.GENERAL_MANAGER], "attendance.scheduling"]
    return await make_user(Role.GENERAL_MANAGER, perms=perms)


async def put(client, actor, users, **body):
    body = {"user_ids": [str(u.id) for u in users], **body}
    return await client.put("/attendance/scheduling/employees", json=body, headers=auth(actor))


async def today_of(client, user) -> dict:
    r = await client.get("/attendance/me/today", headers=auth(user))
    assert r.status_code == 200, r.text
    return r.json()


def times(today: dict) -> list[tuple[str, str, str]]:
    return [(s["code"], s["start"][11:16], s["end"][11:16]) for s in today["shifts"]]


async def backdate(session, *users) -> None:
    await session.execute(
        update(User).where(User.id.in_([u.id for u in users])).values(created_at=at("05:00"))
    )
    await session.commit()


async def holiday(client, actor, start, end=None) -> dict:
    body = {
        "name_km": "ភ្ជុំបិណ្ឌ",
        "name_en": "Pchum Ben",
        "start_date": start,
        "end_date": end or start,
        "scope": "all",
    }
    r = await client.post("/attendance/holidays", json=body, headers=auth(actor))
    assert r.status_code == 201, r.text
    return r.json()["holiday"]


async def work_on(client, actor, h, users, dates, **body):
    return await client.put(
        f"/attendance/holidays/{h['id']}/exceptions",
        json={"user_ids": [str(u.id) for u in users], "dates": dates, **body},
        headers=auth(actor),
    )


async def tick(now):
    return await scheduler.run_tick(now, app.state.telegram)


async def records(session, day) -> set[tuple]:
    from datetime import date

    rows = await session.scalars(
        select(AttendanceRecord)
        .where(AttendanceRecord.work_date == date.fromisoformat(day))
        .execution_options(populate_existing=True)
    )
    return {(r.user_id, r.shift_code, r.status) for r in rows}


# --- The resolver ---------------------------------------------------------------------------------


async def test_done_when_morning_only_from_tomorrow(
    client, session, clock, workplace, make_user, telegram_bot
) -> None:
    """Mon–Sat, morning only 07:30–12:00 from tomorrow: their own windows and reminders, no
    afternoon, Sundays off; everyone else follows the workplace."""
    gm = await scheduler_gm(make_user)
    own = await make_user(Role.STAFF, telegram_user_id=8101)
    other = await make_user(Role.STAFF, telegram_user_id=8102)
    await backdate(session, own, other)
    clock("10:00")
    r = await put(client, gm, [own], effective_from=WED, **morning_only())
    assert r.status_code == 200, r.text
    assert r.json() == {"effective_from": WED, "changed": [str(own.id)], "unchanged": []}

    # Today is unchanged.
    assert times(await today_of(client, own)) == [
        ("morning", "07:00", "12:00"),
        ("afternoon", "13:00", "15:00"),
    ]
    clock(at("06:00", WED))
    today = await today_of(client, own)
    assert times(today) == [("morning", "07:30", "12:00")]
    assert today["shifts"][0]["check_in_opens"][11:16] == "07:00"
    assert today["shifts"][0]["check_in_until"][11:16] == "08:14"
    assert len((await today_of(client, other))["shifts"]) == 2

    # Reminders at their own time: 06:30 for the others, 07:00 for them.
    await tick(at("06:30", WED))
    reminded = set(await session.scalars(select(AttendanceReminder.user_id)))
    assert reminded == {other.id}
    await tick(at("07:00", WED))
    reminded = set(await session.scalars(select(AttendanceReminder.user_id)))
    assert reminded == {other.id, own.id}
    # Absent at their own cutoff (08:15), not the workplace's (07:45).
    await tick(at("07:45", WED))
    assert await records(session, WED) == {(other.id, "morning", "absent")}
    await tick(at("08:15", WED))
    assert (own.id, "morning", "absent") in await records(session, WED)
    # No afternoon is expected of them.
    await tick(at("14:00", WED))
    assert await records(session, WED) == {
        (other.id, "morning", "absent"),
        (own.id, "morning", "absent"),
        (other.id, "afternoon", "absent"),
    }
    # Sunday is a day off for them only.
    clock(at("06:00", SUN))
    today = await today_of(client, own)
    assert today["day_off"]["reason"] == "weekday" and today["shifts"] == []
    assert today["next_action"]["next_opens_at"].startswith("2026-10-19T07:00")
    assert len((await today_of(client, other))["shifts"]) == 2
    await tick(at("14:00", SUN))
    assert await records(session, SUN) == {
        (other.id, "morning", "absent"),
        (other.id, "afternoon", "absent"),
    }
    clock(at("07:10", SUN))
    r = await client.post("/attendance/check-in", json=position(), headers=auth(own))
    assert_error(r, 409, "ATTENDANCE_DAY_OFF")


async def test_check_in_uses_their_own_windows(
    client, session, clock, workplace, make_user
) -> None:
    gm = await scheduler_gm(make_user)
    own = await make_user(Role.STAFF)
    clock("05:00")
    assert (await put(client, gm, [own], **morning_only())).status_code == 200
    clock("06:50")  # the workplace's window is open, theirs (07:00) isn't
    r = await client.post("/attendance/check-in", json=position(), headers=auth(own))
    assert_error(r, 409, "ATTENDANCE_TOO_EARLY")
    clock("07:40")
    r = await client.post("/attendance/check-in", json=position(), headers=auth(own))
    assert r.status_code == 200, r.text
    record = r.json()["record"]
    assert (record["status"], record["late_minutes"]) == ("late", 10)
    assert record["scheduled_start"][11:16] == "07:30"


async def test_inherited_fields_follow_the_workplace(client, clock, workplace, make_user) -> None:
    gm = await scheduler_gm(make_user)
    own = await make_user(Role.STAFF)
    other = await make_user(Role.STAFF)
    clock("05:00")
    body = {"shift_times": {"morning": {"start_time": "07:30", "end_time": "12:00"}}}
    assert (await put(client, gm, [own], **body)).status_code == 200
    r = await client.put(
        "/attendance/scheduling/shifts",
        json=shifts_body(("07:15", "12:00"), ("13:30", "15:30"), effective_from=WED),
        headers=auth(gm),
    )
    assert r.status_code == 200, r.text
    clock(at("05:00", WED))
    assert times(await today_of(client, own)) == [
        ("morning", "07:30", "12:00"),  # their own
        ("afternoon", "13:30", "15:30"),  # inherited: follows the workplace
    ]
    assert times(await today_of(client, other)) == [
        ("morning", "07:15", "12:00"),
        ("afternoon", "13:30", "15:30"),
    ]


async def test_afternoon_only_and_detail(client, clock, workplace, make_user) -> None:
    gm = await scheduler_gm(make_user)
    own = await make_user(Role.STAFF)
    clock("05:00")
    body = {
        "shift_codes": ["afternoon"],
        "shift_times": {"afternoon": {"start_time": "13:30", "end_time": "17:00"}},
    }
    assert (await put(client, gm, [own], **body)).status_code == 200
    assert times(await today_of(client, own)) == [("afternoon", "13:30", "17:00")]
    r = await client.get(f"/attendance/scheduling/employees/{own.id}", headers=auth(gm))
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["schedule"]["custom"] == ["shift_codes", "shift_times"]
    assert d["schedule"]["weekdays"] == [1, 2, 3, 4, 5, 6, 7]
    (shift,) = d["schedule"]["shifts"]
    assert (shift["code"], shift["start_time"], shift["end_time"]) == (
        "afternoon",
        "13:30",
        "17:00",
    )
    assert shift["windows"] == {
        "check_in_opens": "13:00",
        "check_in_until": "14:14",
        "late_after": "13:30",
        "absent_from": "14:15",
        "check_out_opens": "17:00",
        "check_out_until": "17:59",
        "forgot_from": "18:00",
    }
    assert len(d["workplace_schedule"]["shifts"]) == 2
    assert d["workplace_schedule"]["custom"] == []
    assert d["current"]["shift_codes"] == ["afternoon"] and d["current"]["weekdays"] is None
    assert [p["date"] for p in d["preview"]] == [f"2026-10-{n}" for n in range(13, 20)]
    assert d["preview"][0]["shifts"] == [
        {"code": "afternoon", "start_time": "13:30", "end_time": "17:00"}
    ]


async def test_holiday_off_and_exceptions(client, session, clock, workplace, make_user) -> None:
    gm = await scheduler_gm(make_user)
    normal = await make_user(Role.STAFF)
    custom = await make_user(Role.STAFF)
    off = await make_user(Role.STAFF)
    await backdate(session, normal, custom, off)
    clock("05:00")
    h = await holiday(client, gm, THU)
    r = await work_on(client, gm, h, [normal], [THU])
    assert r.status_code == 200, r.text
    r = await work_on(
        client,
        gm,
        h,
        [custom],
        [THU],
        shift_codes=["afternoon"],
        shift_times={"afternoon": {"start_time": "14:00", "end_time": "16:00"}},
    )
    assert r.status_code == 200, r.text
    items = {i["user"]["id"]: i for i in r.json()["items"]}
    assert items[str(custom.id)]["shifts"] == [
        {"code": "afternoon", "start_time": "14:00", "end_time": "16:00"}
    ]
    assert len(items[str(normal.id)]["shifts"]) == 2

    clock(at("05:00", THU))
    assert len((await today_of(client, normal))["shifts"]) == 2
    assert times(await today_of(client, custom)) == [("afternoon", "14:00", "16:00")]
    today = await today_of(client, off)
    assert today["day_off"]["reason"] == "holiday"
    # The scheduler expects only them.
    await tick(at("14:00", THU))
    assert await records(session, THU) == {
        (normal.id, "morning", "absent"),
        (normal.id, "afternoon", "absent"),
    }
    await tick(at("14:45", THU))
    assert (custom.id, "afternoon", "absent") in await records(session, THU)
    # The calendar shows who works.
    r = await client.get("/attendance/calendar?year=2026&month=10", headers=auth(gm))
    day = next(d for d in r.json()["days"] if d["date"] == THU)
    assert (day["status"], day["working"]) == ("off", 2)
    # Preview of the week marks it.
    r = await client.get(f"/attendance/scheduling/employees/{normal.id}", headers=auth(gm))
    preview = {p["date"]: p for p in r.json()["preview"]}
    assert preview[THU]["works_on_holiday"]["id"] == h["id"]
    assert preview[THU]["day_off"] is None


async def test_holiday_exception_with_own_schedule(client, clock, workplace, make_user) -> None:
    """ "Their normal shifts": the employee's own, whatever the weekday."""
    gm = await scheduler_gm(make_user)
    own = await make_user(Role.STAFF)
    clock("05:00")
    assert (await put(client, gm, [own], **morning_only(weekdays=[1, 2]))).status_code == 200
    h = await holiday(client, gm, THU)  # a Thursday, not one of their days
    assert (await work_on(client, gm, h, [own], [THU])).status_code == 200
    clock(at("05:00", THU))
    assert times(await today_of(client, own)) == [("morning", "07:30", "12:00")]


async def test_tracking_comes_first(client, session, clock, workplace, make_user) -> None:
    from datetime import date

    gm = await scheduler_gm(make_user)
    later = await make_user(Role.STAFF)
    await session.execute(
        update(User).where(User.id == later.id).values(attendance_start_date=date(2026, 10, 20))
    )
    await session.commit()
    clock("05:00")
    assert (await put(client, gm, [later], **morning_only())).status_code == 200
    today = await today_of(client, later)
    assert today["shifts"] == [] and today["starts_on"] == "2026-10-20"
    await backdate(session, later)
    await tick(at("14:00"))
    assert await records(session, TUE) == set()


# --- Validation and conflicts ---------------------------------------------------------------------


async def test_invalid_times(client, clock, workplace, make_user) -> None:
    gm = await scheduler_gm(make_user)
    own = await make_user(Role.STAFF)
    clock("05:00")
    for morning in (("12:00", "11:00"), ("11:00", "13:30"), ("00:10", "06:00")):
        body = {"shift_times": {"morning": {"start_time": morning[0], "end_time": morning[1]}}}
        r = await put(client, gm, [own], **body)
        assert_error(r, 422, "ATTENDANCE_SCHEDULE_INVALID")
        details = r.json()["error"]["details"]
        assert details["user_id"] == str(own.id)
        assert details["fields"][0]["loc"][:2] == ["body", "shift_times"]
    r = await put(client, gm, [own], shift_codes=[])
    assert_error(r, 422, "VALIDATION_ERROR")
    r = await put(client, gm, [own], weekdays=None)
    assert_error(r, 422, "VALIDATION_ERROR")
    r = await client.get(f"/attendance/scheduling/employees/{own.id}", headers=auth(gm))
    assert r.json()["current"] is None


async def test_workplace_change_conflicts(client, session, clock, workplace, make_user) -> None:
    gm = await scheduler_gm(make_user)
    own = await make_user(Role.STAFF, username="own_times")
    clock("05:00")
    body = {"shift_times": {"morning": {"start_time": "07:30", "end_time": "12:30"}}}
    assert (await put(client, gm, [own], **body)).status_code == 200
    # The workplace's afternoon would now start inside their morning.
    r = await client.put(
        "/attendance/scheduling/shifts",
        json=shifts_body(afternoon=("12:00", "15:00")),
        headers=auth(gm),
    )
    assert_error(r, 409, "ATTENDANCE_SCHEDULE_CONFLICT")
    (employee,) = r.json()["error"]["details"]["employees"]
    assert employee["user_id"] == str(own.id)
    # Nothing was saved.
    clock("05:01")
    assert times(await today_of(client, own))[1] == ("afternoon", "13:00", "15:00")
    # An upcoming override is checked too.
    r = await client.put(
        "/attendance/scheduling/shifts",
        json=shifts_body(afternoon=("12:00", "15:00"), effective_from="2026-11-01"),
        headers=auth(gm),
    )
    assert_error(r, 409, "ATTENDANCE_SCHEDULE_CONFLICT")
    # A change that fits is fine.
    r = await client.put(
        "/attendance/scheduling/shifts",
        json=shifts_body(afternoon=("13:30", "15:00")),
        headers=auth(gm),
    )
    assert r.status_code == 200, r.text
    assert r.json()["affected_employees"] == []


async def test_removed_shift_codes_leave_overrides(
    client, session, clock, workplace, make_user
) -> None:
    gm = await scheduler_gm(make_user)
    one, both = await make_user(Role.STAFF), await make_user(Role.STAFF)
    clock("05:00")
    body = {
        "shift_codes": ["afternoon"],
        "shift_times": {"afternoon": {"start_time": "13:30", "end_time": "15:00"}},
    }
    assert (await put(client, gm, [one], **body)).status_code == 200
    assert (await put(client, gm, [both], shift_codes=["morning", "afternoon"])).status_code == 200
    affected = await ovr.prune_codes(session, [workplace], {"afternoon"})
    await session.commit()
    assert {a["user_id"] for a in affected} == {str(one.id), str(both.id)}
    rows = {
        o.user_id: o
        for o in await session.scalars(
            select(AttendanceEmployeeOverride).execution_options(populate_existing=True)
        )
    }
    # Left with no shifts: inherits them all again.
    assert (rows[one.id].shift_codes, rows[one.id].shift_times) == (None, None)
    assert rows[both.id].shift_codes == ["morning"]


# --- Effective dates ------------------------------------------------------------------------------


async def test_effective_today_only_unopened_shifts(
    client, session, clock, workplace, make_user
) -> None:
    gm = await scheduler_gm(make_user)
    own = await make_user(Role.STAFF)
    clock("07:10")  # the morning check-in is open
    body = {
        "shift_times": {
            "morning": {"start_time": "08:00", "end_time": "12:00"},
            "afternoon": {"start_time": "13:30", "end_time": "15:00"},
        }
    }
    assert (await put(client, gm, [own], **body)).status_code == 200
    # Today: the morning keeps 07:00, the afternoon (not open yet) moves.
    assert times(await today_of(client, own)) == [
        ("morning", "07:00", "12:00"),
        ("afternoon", "13:30", "15:00"),
    ]
    row = await session.scalar(select(AttendanceEmployeeOverride))
    assert row.kept_shifts == {"morning": {"start_time": "07:00", "end_time": "12:00"}}
    clock(at("05:00", WED))
    assert times(await today_of(client, own))[0] == ("morning", "08:00", "12:00")


async def test_effective_today_new_shift_already_open_is_skipped(
    client, clock, workplace, make_user
) -> None:
    """A shift added back after its window opened isn't worked today."""
    gm = await scheduler_gm(make_user)
    own = await make_user(Role.STAFF)
    clock("05:00")
    assert (await put(client, gm, [own], shift_codes=["afternoon"])).status_code == 200
    assert [s[0] for s in times(await today_of(client, own))] == ["afternoon"]
    clock("10:00")
    assert (await put(client, gm, [own], shift_codes="inherit")).status_code == 200
    # The morning (opened at 06:30) stays off today; from tomorrow both.
    assert [s[0] for s in times(await today_of(client, own))] == ["afternoon"]
    clock(at("05:00", WED))
    assert [s[0] for s in times(await today_of(client, own))] == ["morning", "afternoon"]


async def test_versions_past_upcoming_delete_reset(
    client, session, clock, workplace, make_user
) -> None:
    gm = await scheduler_gm(make_user)
    own = await make_user(Role.STAFF)
    clock("05:00")
    r = await put(client, gm, [own], effective_from="2026-10-12", weekdays=MON_SAT)
    assert_error(r, 422, "VALIDATION_ERROR")
    assert (await put(client, gm, [own], weekdays=MON_SAT)).status_code == 200
    assert (
        await put(client, gm, [own], effective_from="2026-11-01", shift_codes=["morning"])
    ).status_code == 200
    # Same date replaces; a missing field keeps the value in effect then.
    assert (
        await put(client, gm, [own], effective_from="2026-11-01", shift_codes=["afternoon"])
    ).status_code == 200
    d = (await client.get(f"/attendance/scheduling/employees/{own.id}", headers=auth(gm))).json()
    assert d["current"]["weekdays"] == MON_SAT
    (upcoming,) = d["upcoming"]
    assert (upcoming["weekdays"], upcoming["shift_codes"]) == (MON_SAT, ["afternoon"])
    # The same value again changes nothing.
    r = await put(client, gm, [own], weekdays=MON_SAT)
    assert r.json()["unchanged"] == [str(own.id)]
    # A change from today also holds in the upcoming version.
    assert (await put(client, gm, [own], weekdays=[1, 2, 3])).status_code == 200
    d = (await client.get(f"/attendance/scheduling/employees/{own.id}", headers=auth(gm))).json()
    assert d["upcoming"][0]["weekdays"] == [1, 2, 3]
    # Only upcoming versions can be deleted.
    url = f"/attendance/scheduling/employees/{own.id}/versions"
    r = await client.delete(f"{url}/{d['current']['id']}", headers=auth(gm))
    assert_error(r, 409, "ATTENDANCE_SCHEDULE_VERSION_IN_EFFECT")
    r = await client.delete(f"{url}/{d['upcoming'][0]['id']}", headers=auth(gm))
    assert r.status_code == 204, r.text
    assert (
        await put(client, gm, [own], effective_from="2026-11-01", shift_codes=["morning"])
    ).status_code == 200
    # Reset: everything inherits, later versions go.
    r = await client.post(
        "/attendance/scheduling/employees/reset",
        json={"user_ids": [str(own.id)]},
        headers=auth(gm),
    )
    assert r.json()["changed"] == [str(own.id)]
    d = (await client.get(f"/attendance/scheduling/employees/{own.id}", headers=auth(gm))).json()
    assert d["upcoming"] == [] and d["schedule"]["custom"] == []
    assert d["current"]["weekdays"] is None
    actions = list(await session.scalars(select(AuditLog.action).order_by(AuditLog.created_at)))
    assert "attendance.employee_schedule_update" in actions
    assert "attendance.employee_schedule_version_delete" in actions
    assert actions[-1] == "attendance.employee_schedule_reset"


# --- Bulk, scope, list ----------------------------------------------------------------------------


async def test_bulk_scope_and_list(
    client, session, clock, workplace, make_user, superadmin
) -> None:
    gm = await scheduler_gm(make_user)
    a, b = await make_user(Role.STAFF), await make_user(Role.STAFF)
    sup = await make_user(Role.SUPERVISOR)
    clock("05:00")
    r = await put(client, gm, [a, b, sup], shift_codes=["morning"])
    assert r.status_code == 200, r.text
    assert set(r.json()["changed"]) == {str(a.id), str(b.id), str(sup.id)}
    audit = await session.scalar(
        select(AuditLog).where(AuditLog.action == "attendance.employee_schedule_update")
    )
    assert len(audit.details["user_ids"]) == 3
    assert audit.details["changes"][a.full_name]["shift_codes"] == ["inherit", ["morning"]]
    # One notification each.
    assert await session.scalar(
        select(Notification).where(Notification.type == "attendance.schedule_changed").limit(1)
    )
    count = len(
        list(
            await session.scalars(
                select(Notification.user_id).where(
                    Notification.type == "attendance.schedule_changed"
                )
            )
        )
    )
    assert count == 3

    # A supervisor with the permission: staff only.
    lead = await make_user(
        Role.SUPERVISOR, perms=[*DEFAULT_PERMISSIONS[Role.SUPERVISOR], "attendance.scheduling"]
    )
    assert (await put(client, lead, [a], weekdays=MON_SAT)).status_code == 200
    assert_error(await put(client, lead, [sup], weekdays=MON_SAT), 403, "FORBIDDEN_SCOPE")
    listed = (await client.get("/attendance/scheduling/employees", headers=auth(lead))).json()
    assert {i["user"]["id"] for i in listed["items"]} == {str(a.id), str(b.id)}
    # Hidden accounts are 404; untracked roles 422; no permission 403.
    assert_error(await put(client, gm, [superadmin], weekdays=MON_SAT), 404, "USER_NOT_FOUND")
    other_gm = await make_user(Role.GENERAL_MANAGER)
    assert_error(await put(client, gm, [other_gm], weekdays=MON_SAT), 403, "FORBIDDEN_SCOPE")
    assert_error(await put(client, other_gm, [a], weekdays=MON_SAT), 403, "MISSING_PERMISSION")
    r = await client.get(f"/attendance/scheduling/employees/{superadmin.id}", headers=auth(gm))
    assert_error(r, 404, "USER_NOT_FOUND")

    # The list: summaries, custom only, search, workplace filter.
    plain = await make_user(Role.STAFF)
    listed = (await client.get("/attendance/scheduling/employees", headers=auth(gm))).json()
    rows = {i["user"]["id"]: i for i in listed["items"]}
    assert rows[str(a.id)]["summary"]["custom"] == ["weekdays", "shift_codes"]
    assert rows[str(plain.id)]["summary"]["custom"] == []
    assert listed["items"][0]["role"] == "supervisor"
    r = await client.get("/attendance/scheduling/employees?custom_only=true", headers=auth(gm))
    assert str(plain.id) not in {i["user"]["id"] for i in r.json()["items"]}
    r = await client.get(
        f"/attendance/scheduling/employees?workplace_ids={workplace.id}", headers=auth(gm)
    )
    assert len(r.json()["items"]) == 5
    await put(client, gm, [plain], effective_from="2026-11-01", weekdays=MON_SAT)
    r = await client.get("/attendance/scheduling/employees?custom_only=true", headers=auth(gm))
    row = next(i for i in r.json()["items"] if i["user"]["id"] == str(plain.id))
    assert (row["upcoming"], row["next_change"]) == (1, "2026-11-01")

    # The user page's summary (attendance.view or attendance.scheduling).
    user = (await client.get(f"/users/{a.id}", headers=auth(gm))).json()
    assert user["attendance_schedule_summary"]["weekdays"] == MON_SAT
    assert user["attendance_schedule_summary"]["custom"] == ["weekdays", "shift_codes"]


# --- Holiday exceptions: rules and cleanup --------------------------------------------------------


async def test_exception_rules(client, session, clock, workplace, make_user) -> None:
    gm = await scheduler_gm(make_user)
    own = await make_user(Role.STAFF)
    clock("05:00")
    h = await holiday(client, gm, "2026-10-12", THU)
    r = await work_on(client, gm, h, [own], ["2026-10-12"])
    assert_error(r, 422, "VALIDATION_ERROR")  # past
    r = await work_on(client, gm, h, [own], ["2026-10-20"])
    assert_error(r, 422, "VALIDATION_ERROR")  # outside the holiday
    body = {"shift_times": {"morning": {"start_time": "11:00", "end_time": "13:30"}}}
    r = await work_on(client, gm, h, [own], [WED], **body)
    assert_error(r, 422, "ATTENDANCE_SCHEDULE_INVALID")
    r = await work_on(client, gm, h, [own], [WED, THU])
    assert r.status_code == 200 and len(r.json()["items"]) == 2
    # Notifications and audit.
    types = list(await session.scalars(select(Notification.type)))
    assert types.count("attendance.holiday_work") == 2
    # Shortening the holiday drops the exceptions outside it.
    r = await client.patch(
        f"/attendance/holidays/{h['id']}",
        json={
            "name_km": "ភ្ជុំបិណ្ឌ",
            "name_en": "Pchum Ben",
            "start_date": "2026-10-12",
            "end_date": WED,
            "scope": "all",
        },
        headers=auth(gm),
    )
    assert r.status_code == 200, r.text
    left = list(
        await session.scalars(
            select(AttendanceHolidayException).execution_options(populate_existing=True)
        )
    )
    assert [e.day.isoformat() for e in left] == [WED]


async def test_exception_today_and_its_removal(
    client, session, clock, workplace, make_user
) -> None:
    gm = await scheduler_gm(make_user)
    early, late = await make_user(Role.STAFF), await make_user(Role.STAFF)
    await backdate(session, early, late)
    clock("05:00")
    h = await holiday(client, gm, TUE)
    assert (await work_on(client, gm, h, [early], [TUE])).status_code == 200
    # Set once the morning opened: only the afternoon is theirs today.
    clock("08:00")
    assert (await work_on(client, gm, h, [late], [TUE])).status_code == 200
    assert [s[0] for s in times(await today_of(client, late))] == ["afternoon"]
    assert len((await today_of(client, early))["shifts"]) == 2
    clock("07:00")
    r = await client.post("/attendance/check-in", json=position(), headers=auth(early))
    assert r.status_code == 200, r.text

    # Removed for today: off again, their records go.
    clock("09:00")
    exceptions = (
        await client.get(f"/attendance/holidays/{h['id']}/exceptions", headers=auth(gm))
    ).json()["items"]
    mine = next(e for e in exceptions if e["user"]["id"] == str(early.id))
    r = await client.delete(
        f"/attendance/holidays/{h['id']}/exceptions/{mine['id']}", headers=auth(gm)
    )
    assert r.status_code == 200, r.text
    assert r.json()["records_removed"] == 1
    assert await records(session, TUE) == set()
    assert (await today_of(client, early))["day_off"]["reason"] == "holiday"
    actions = set(await session.scalars(select(AuditLog.action)))
    assert {
        "attendance.records_removed_by_day_off",
        "attendance.holiday_exception_delete",
        "attendance.holiday_exception_create",
    } <= actions
    off = await session.scalar(
        select(Notification).where(Notification.type == "attendance.holiday_off")
    )
    assert off.user_id == early.id
    text, keyboard = message_for(off, Language.EN)
    assert text == "📅 You're off on Pchum Ben (Tue 13 Oct 2026)."


async def test_weekday_change_keeps_records_of_own_weekdays(
    client, session, clock, workplace, make_user
) -> None:
    """Today untracked at the workplace: someone whose own weekdays include today keeps working
    and keeps their record."""
    gm = await scheduler_gm(make_user)
    own, other = await make_user(Role.STAFF), await make_user(Role.STAFF)
    clock("05:00")
    assert (await put(client, gm, [own], weekdays=[1, 2, 3, 4, 5, 6, 7])).status_code == 200
    clock("07:00")
    for u in (own, other):
        r = await client.post("/attendance/check-in", json=position(), headers=auth(u))
        assert r.status_code == 200, r.text
    r = await client.put(
        "/attendance/scheduling/weekdays",
        json={"workplace_ids": "all", "weekdays": [1, 3, 4, 5, 6, 7]},
        headers=auth(gm),
    )
    assert r.json()["records_removed"] == 1
    assert {u for u, _, _ in await records(session, TUE)} == {own.id}


# --- Views ----------------------------------------------------------------------------------------


async def test_day_view_and_summary(client, session, clock, workplace, make_user) -> None:
    gm = await scheduler_gm(make_user)
    own, other = await make_user(Role.STAFF), await make_user(Role.STAFF)
    await backdate(session, own, other)
    clock("05:00")
    assert (await put(client, gm, [own], **morning_only())).status_code == 200
    day = (await client.get("/attendance/day", headers=auth(gm))).json()
    rows = {r["user"]["id"]: r for r in day["rows"]}
    assert rows[str(own.id)]["shifts"]["afternoon"]["state"] == "not_expected"
    morning = rows[str(own.id)]["shifts"]["morning"]
    assert (morning["state"], morning["start"], morning["end"]) == ("not_yet", "07:30", "12:00")
    assert rows[str(other.id)]["shifts"]["morning"]["start"] is None
    kpis = {s["code"]: s["kpis"]["expected"] for s in day["shifts"]}
    assert kpis == {"morning": 2, "afternoon": 1}

    # A Sunday is a day off in their summary only.
    clock(at("20:00", SUN))
    summary = (
        await client.get(f"/attendance/users/{own.id}/summary?year=2026&month=10", headers=auth(gm))
    ).json()
    sunday = next(d for d in summary["days"] if d["date"] == SUN)
    assert sunday["day_off"]["reason"] == "weekday"
    summary = (
        await client.get(
            f"/attendance/users/{other.id}/summary?year=2026&month=10", headers=auth(gm)
        )
    ).json()
    assert next(d for d in summary["days"] if d["date"] == SUN)["day_off"] is None


async def test_schedule_message(client, session, clock, workplace, make_user) -> None:
    gm = await scheduler_gm(make_user)
    own = await make_user(Role.STAFF)
    clock("05:00")
    assert (await put(client, gm, [own], effective_from=WED, **morning_only())).status_code == 200
    n = await session.scalar(select(Notification))
    assert n.user_id == own.id
    text, keyboard = message_for(n, Language.EN)
    assert text == (
        "📅 Your attendance schedule changes from Wed 14 Oct 2026: Mon–Sat · Morning 07:30–12:00."
    )
    km, _ = message_for(n, Language.KM)
    assert "ច័ន្ទ–សៅរ៍" in km
