"""A whole day's sequence: an absent shift needs no check-out and doesn't block the next shift; a
late shift still needs one (else `late` + forgot check-out). `next_action` and scheduler ticks
across the default schedule (morning 07:00–12:00, afternoon 13:00–15:00; check-in from 30 min
before, absent from 45 min after the start, check-out until 59 min after the end)."""

from sqlalchemy import select, update

from app.attendance import scheduler
from app.models import AttendanceRecord, Role, User
from tests.conftest import assert_error, at, auth, position


async def _setup(session, make_user):
    staff = await make_user(Role.STAFF)
    # Existing since the early morning (the scheduler only counts people who existed then).
    await session.execute(update(User).where(User.id == staff.id).values(created_at=at("05:00")))
    await session.commit()
    return staff


async def _next(client, user) -> dict:
    r = await client.get("/attendance/me/today", headers=auth(user))
    assert r.status_code == 200, r.text
    return r.json()["next_action"]


async def _record(session, user, shift: str) -> AttendanceRecord | None:
    return await session.scalar(
        select(AttendanceRecord)
        .where(AttendanceRecord.user_id == user.id, AttendanceRecord.shift_code == shift)
        .execution_options(populate_existing=True)
    )


async def _check(client, user, action="check-in"):
    return await client.post(f"/attendance/{action}", json=position(), headers=auth(user))


async def test_absent_morning_needs_no_check_out(
    client, session, clock, workplace, make_user
) -> None:
    staff = await _setup(session, make_user)
    clock("07:30")
    assert (await _next(client, staff))["action"] == "check_in"

    # 07:45: the morning is absent; nothing is due until the afternoon check-in (12:30), not
    # the morning check-out.
    clock("07:45")
    await scheduler.tick(session, at("07:45"))
    await session.commit()
    assert (await _record(session, staff, "morning")).status == "absent"
    na = await _next(client, staff)
    assert (na["action"], na["next_action"], na["next_shift_code"]) == (
        "none",
        "check_in",
        "afternoon",
    )
    assert na["next_opens_at"].startswith("2026-10-13T12:30:00+07:00")

    # 12:10, inside the morning's check-out window: refused, nothing to check out.
    clock("12:10")
    r = await _check(client, staff, "check-out")
    assert_error(r, 409, "ATTENDANCE_NOT_CHECKED_IN")
    assert r.json()["error"]["details"]["shift_code"] == "morning"
    assert (await _next(client, staff))["next_action"] == "check_in"

    # 12:40: the afternoon check-in works as usual.
    clock("12:40")
    assert (await _next(client, staff))["action"] == "check_in"
    r = await _check(client, staff)
    assert r.status_code == 200, r.text
    assert r.json()["record"]["shift_code"] == "afternoon"

    # 13:00: the morning check-out window closed: never "forgot check-out".
    await scheduler.tick(session, at("13:00"))
    await session.commit()
    morning = await _record(session, staff, "morning")
    assert (morning.status, morning.checkout_status) == ("absent", None)

    clock("15:05")
    assert (await _next(client, staff))["action"] == "check_out"
    assert (await _check(client, staff, "check-out")).status_code == 200
    na = await _next(client, staff)
    assert (na["action"], na["next_action"]) == ("none", "check_in")
    assert na["next_opens_at"].startswith("2026-10-14T06:30:00+07:00")


async def test_late_morning_still_needs_a_check_out(
    client, session, clock, workplace, make_user
) -> None:
    staff = await _setup(session, make_user)
    clock("07:20")
    rec = (await _check(client, staff)).json()["record"]
    assert (rec["status"], rec["late_minutes"]) == ("late", 20)
    na = await _next(client, staff)
    assert (na["action"], na["next_action"], na["next_shift_code"]) == (
        "none",
        "check_out",
        "morning",
    )

    # 12:30–12:59: the morning check-out comes before the afternoon check-in.
    clock("12:30")
    na = await _next(client, staff)
    assert (na["action"], na["shift_code"]) == ("check_out", "morning")

    # Missed: at 13:00 the record stays late with "forgot check-out".
    await scheduler.tick(session, at("13:00"))
    await session.commit()
    morning = await _record(session, staff, "morning")
    assert (morning.status, morning.checkout_status, morning.late_minutes) == (
        "late",
        "forgot_checkout",
        20,
    )
    assert morning.overtime_minutes == 0
    clock("13:00")
    assert (await _next(client, staff))["action"] == "check_in"


async def test_late_morning_checked_out(client, session, clock, workplace, make_user) -> None:
    staff = await _setup(session, make_user)
    clock("07:05")
    await _check(client, staff)
    clock("12:10")
    r = await _check(client, staff, "check-out")
    assert r.status_code == 200, r.text
    rec = r.json()["record"]
    assert (rec["status"], rec["checkout_status"]) == ("late", "checked_out")
    await scheduler.tick(session, at("13:00"))
    await session.commit()
    assert (await _record(session, staff, "morning")).checkout_status == "checked_out"
    clock("12:40")
    na = await _next(client, staff)
    assert (na["action"], na["shift_code"]) == ("check_in", "afternoon")


async def test_both_shifts_absent(client, session, clock, workplace, make_user) -> None:
    staff = await _setup(session, make_user)
    await scheduler.tick(session, at("07:45"))
    await scheduler.tick(session, at("13:45"))
    await scheduler.tick(session, at("16:00"))
    await session.commit()
    for shift in ("morning", "afternoon"):
        rec = await _record(session, staff, shift)
        assert (rec.status, rec.checkout_status) == ("absent", None)
    clock("15:10")
    assert_error(await _check(client, staff, "check-out"), 409, "ATTENDANCE_NOT_CHECKED_IN")
    na = await _next(client, staff)
    assert (na["action"], na["next_action"]) == ("none", "check_in")
    assert na["next_opens_at"].startswith("2026-10-14T06:30:00+07:00")
