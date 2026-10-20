"""Early check-in and overtime: minutes at check-in / check-out (limits, forgot check-out = 0), the
workplace flags snapshotted on the record, recomputation on corrections, the schedule flags."""

from datetime import timedelta

from sqlalchemy import select

from app.attendance import scheduler
from app.attendance import windows as win
from app.models import AttendanceRecord, Role
from tests.conftest import at, auth, position, set_schedule


async def _check(client, user, action="check-in"):
    r = await client.post(f"/attendance/{action}", json=position(), headers=auth(user))
    assert r.status_code == 200, r.text
    return r.json()["record"]


def test_minutes_functions() -> None:
    start = at("07:00")
    assert win.early_minutes(at("06:40:30"), start, 30) == 20  # the minute people read
    assert win.early_minutes(at("06:59:59"), start, 30) == 1
    assert win.early_minutes(at("07:00"), start, 30) == 0
    assert win.early_minutes(at("07:10"), start, 30) == 0
    assert win.early_minutes(at("05:00"), start, 30) == 30  # capped
    end = at("12:00")
    assert win.overtime_minutes(at("12:25:40"), end, 59) == 25
    assert win.overtime_minutes(at("12:00:59"), end, 59) == 0
    assert win.overtime_minutes(at("11:50"), end, 59) == 0
    assert win.overtime_minutes(at("14:00"), end, 59) == 59  # capped
    assert win.overtime_minutes(None, end, 59) == 0


async def test_early_check_in_and_overtime(client, clock, workplace, make_user) -> None:
    staff = await make_user(Role.STAFF)
    clock("06:40:30")
    rec = await _check(client, staff)
    assert (rec["status"], rec["early_minutes"], rec["late_minutes"]) == ("present", 20, 0)
    assert (rec["early_counts"], rec["overtime_counts"]) == (True, True)
    assert rec["overtime_minutes"] == 0
    clock("12:25:40")
    rec = await _check(client, staff, "check-out")
    assert (rec["early_minutes"], rec["overtime_minutes"]) == (20, 25)


async def test_limits_at_the_window_edges(client, clock, workplace, make_user) -> None:
    staff = await make_user(Role.STAFF)
    clock("06:30")  # the first minute of check-in (open 30 min before)
    assert (await _check(client, staff))["early_minutes"] == 30
    clock("12:59:59")  # the last second of the check-out window (59 min)
    assert (await _check(client, staff, "check-out"))["overtime_minutes"] == 59


async def test_late_and_on_time_have_no_early(client, clock, workplace, make_user) -> None:
    staff = await make_user(Role.STAFF)
    clock("07:12")
    rec = await _check(client, staff)
    assert (rec["late_minutes"], rec["early_minutes"]) == (12, 0)
    clock("12:00:30")
    assert (await _check(client, staff, "check-out"))["overtime_minutes"] == 0


async def test_forgot_check_out_has_no_overtime(
    client, session, clock, workplace, make_user
) -> None:
    staff = await make_user(Role.STAFF)
    clock("06:50")
    await _check(client, staff)
    await scheduler.tick(session, at("13:00"))
    await session.commit()
    rec = await session.scalar(select(AttendanceRecord).execution_options(populate_existing=True))
    assert (rec.checkout_status, rec.early_minutes, rec.overtime_minutes) == (
        "forgot_checkout",
        10,
        0,
    )


async def test_flags_off_store_zero(client, session, clock, workplace, make_user) -> None:
    await set_schedule(session, workplace, count_early_checkin=False, count_overtime=False)
    staff = await make_user(Role.STAFF)
    clock("06:40")
    rec = await _check(client, staff)
    assert (rec["early_minutes"], rec["early_counts"], rec["overtime_counts"]) == (0, False, False)
    clock("12:30")
    assert (await _check(client, staff, "check-out"))["overtime_minutes"] == 0


async def test_flags_are_snapshotted(client, session, clock, workplace, make_user) -> None:
    """Switching overtime off after the check-in doesn't change this record; switching it on
    doesn't either."""
    staff = await make_user(Role.STAFF)
    clock("06:45")
    await _check(client, staff)
    await set_schedule(session, workplace, count_overtime=False)
    clock("12:10")
    rec = await _check(client, staff, "check-out")
    assert (rec["overtime_counts"], rec["overtime_minutes"]) == (True, 10)

    # The afternoon is created with the flag off: its check-out counts nothing, even after the
    # flag is back on.
    clock("12:40")
    rec = await _check(client, staff)
    assert (rec["overtime_counts"], rec["early_minutes"]) == (False, 20)
    await set_schedule(session, workplace, count_overtime=True)
    clock("15:20")
    assert (await _check(client, staff, "check-out"))["overtime_minutes"] == 0


async def test_corrections_recompute(client, session, clock, workplace, make_user) -> None:
    gm = await make_user(Role.GENERAL_MANAGER)
    staff = await make_user(Role.STAFF)
    clock("07:10")
    rec = await _check(client, staff)
    clock("09:00")

    async def fix(body: dict) -> dict:
        r = await client.patch(
            f"/attendance/records/{rec['id']}", json={**body, "reason": "Fix"}, headers=auth(gm)
        )
        assert r.status_code == 200, r.text
        return r.json()

    got = await fix({"status": "present", "check_in_time": "06:50", "check_out_time": "12:20"})
    assert (got["status"], got["late_minutes"], got["early_minutes"]) == ("present", 0, 10)
    assert got["overtime_minutes"] == 20
    # Beyond the windows: capped by the workplace's open-before / check-out window.
    got = await fix({"status": "present", "check_in_time": "05:00", "check_out_time": "14:30"})
    assert (got["early_minutes"], got["overtime_minutes"]) == (30, 59)
    got = await fix(
        {"status": "present", "check_in_time": "07:05", "checkout_status": "forgot_checkout"}
    )
    assert (got["late_minutes"], got["early_minutes"], got["overtime_minutes"]) == (5, 0, 0)
    got = await fix({"status": "absent"})
    assert (got["late_minutes"], got["early_minutes"], got["overtime_minutes"]) == (0, 0, 0)
    # Audited with the minutes.
    from app.models import AuditLog

    entry = (
        await session.scalars(
            select(AuditLog)
            .where(AuditLog.action == "attendance.correct")
            .order_by(AuditLog.created_at)
        )
    ).first()
    assert entry.details["after"]["early_minutes"] == 10
    assert entry.details["after"]["overtime_minutes"] == 20


async def test_correction_uses_the_record_snapshot(
    client, session, clock, workplace, make_user
) -> None:
    """A record created with overtime off keeps 0 after a correction, even once it's on."""
    gm = await make_user(Role.GENERAL_MANAGER)
    staff = await make_user(Role.STAFF)
    await set_schedule(session, workplace, count_overtime=False)
    clock("06:50")
    rec = await _check(client, staff)
    await set_schedule(session, workplace, count_overtime=True)
    clock("13:10")
    r = await client.patch(
        f"/attendance/records/{rec['id']}",
        json={
            "status": "present",
            "check_in_time": "06:50",
            "check_out_time": "12:30",
            "reason": "Forgot",
        },
        headers=auth(gm),
    )
    got = r.json()
    assert (got["early_minutes"], got["overtime_minutes"], got["overtime_counts"]) == (
        10,
        0,
        False,
    )


async def test_added_record_snapshots_the_flags(
    client, session, clock, workplace, make_user
) -> None:
    gm = await make_user(Role.GENERAL_MANAGER)
    staff = await make_user(Role.STAFF)
    await set_schedule(session, workplace, count_early_checkin=False)
    clock("16:00")
    r = await client.post(
        "/attendance/records",
        json={
            "user_id": str(staff.id),
            "work_date": (at("16:00") - timedelta(days=1)).date().isoformat(),
            "shift_code": "morning",
            "status": "present",
            "check_in_time": "06:45",
            "check_out_time": "12:15",
            "reason": "On paper",
        },
        headers=auth(gm),
    )
    assert r.status_code == 201, r.text
    got = r.json()
    assert (got["early_counts"], got["early_minutes"]) == (False, 0)
    assert (got["overtime_counts"], got["overtime_minutes"]) == (True, 15)
