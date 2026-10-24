"""Check-in / check-out from the Mini App: windows by the server's clock, location rules, order and
duplicates, refused attempts audited, snapshots, `me/today` and the Telegram confirmation."""

import pytest
from sqlalchemy import select, update

from app.models import AttendanceRecord, AuditLog, Role, User
from tests.conftest import assert_error, at, auth, position, set_schedule


@pytest.fixture
async def staff(make_user):
    return await make_user(Role.STAFF, telegram_user_id=5001)


async def _check(client, user, action="check-in", **pos):
    return await client.post(f"/attendance/{action}", json=position(**pos), headers=auth(user))


async def test_on_time_check_in_and_check_out(client, session, clock, workplace, staff) -> None:
    clock("06:55")
    r = await _check(client, staff, metres_north=35)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["action"] == "check_in"
    rec = body["record"]
    assert (rec["status"], rec["late_minutes"], rec["shift_code"]) == ("present", 0, "morning")
    assert rec["check_in_at"].startswith("2026-10-13T06:55:00+07:00")
    assert rec["check_in_distance_m"] == pytest.approx(35, abs=0.2)
    assert rec["scheduled_start"].startswith("2026-10-13T07:00:00+07:00")
    assert body["today"]["next_action"]["next_action"] == "check_out"

    clock("12:03")
    r = await _check(client, staff, action="check-out", metres_north=10)
    assert r.status_code == 200, r.text
    rec = r.json()["record"]
    assert rec["checkout_status"] == "checked_out"
    assert rec["check_out_at"].startswith("2026-10-13T12:03:00+07:00")


async def test_late_minutes(client, clock, workplace, staff) -> None:
    clock("07:10:40")
    rec = (await _check(client, staff)).json()["record"]
    assert (rec["status"], rec["late_minutes"]) == ("late", 10)


@pytest.mark.parametrize(
    ("hm", "code", "details"),
    [
        ("06:29", "ATTENDANCE_TOO_EARLY", {"shift_code": "morning"}),
        ("07:45", "ATTENDANCE_CHECKIN_CLOSED", {"shift_code": "morning"}),
        ("12:10", "ATTENDANCE_NO_SHIFT_NOW", {"next_shift_code": "afternoon"}),
        ("13:45", "ATTENDANCE_CHECKIN_CLOSED", {"shift_code": "afternoon"}),
        ("15:30", "ATTENDANCE_NO_SHIFT_NOW", {"next_shift_code": "morning"}),
    ],
)
async def test_check_in_windows(client, session, clock, workplace, staff, hm, code, details):
    clock(hm)
    r = await _check(client, staff)
    assert_error(r, 409, code)
    got = r.json()["error"]["details"]
    for key, value in details.items():
        assert got[key] == value
    if code == "ATTENDANCE_TOO_EARLY":
        assert got["opens_at"].startswith("2026-10-13T06:30:00+07:00")
    if code == "ATTENDANCE_NO_SHIFT_NOW" and hm == "12:10":
        assert got["next_opens_at"].startswith("2026-10-13T12:30:00+07:00")
    # Refused: audited, no record.
    assert await session.scalar(select(AttendanceRecord.id)) is None
    entry = await session.scalar(
        select(AuditLog).where(AuditLog.action == "attendance.attempt_refused")
    )
    assert entry is not None and entry.details["code"] == code
    assert entry.target_user_id == staff.id


async def test_afternoon_check_in(client, clock, workplace, staff) -> None:
    clock("13:05")
    rec = (await _check(client, staff)).json()["record"]
    assert (rec["shift_code"], rec["status"], rec["late_minutes"]) == ("afternoon", "late", 5)


@pytest.mark.parametrize(
    ("hm", "code"),
    [
        ("11:59", "ATTENDANCE_CHECKOUT_TOO_EARLY"),
        ("16:00", "ATTENDANCE_CHECKOUT_CLOSED"),
    ],
)
async def test_check_out_windows(client, clock, workplace, staff, hm, code) -> None:
    clock("07:00")
    assert (await _check(client, staff)).status_code == 200
    clock(hm)
    r = await _check(client, staff, action="check-out")
    assert_error(r, 409, code)
    if code == "ATTENDANCE_CHECKOUT_TOO_EARLY":
        assert r.json()["error"]["details"]["opens_at"].startswith("2026-10-13T12:00:00+07:00")


async def test_check_out_until_the_closing_minute(client, clock, workplace, staff) -> None:
    clock("07:00")
    await _check(client, staff)
    clock("12:59:59")
    assert (await _check(client, staff, action="check-out")).status_code == 200


async def test_duplicates_and_order(client, session, clock, workplace, staff) -> None:
    clock("12:10")
    assert_error(await _check(client, staff, action="check-out"), 409, "ATTENDANCE_NOT_CHECKED_IN")
    clock("07:00")
    assert (await _check(client, staff)).status_code == 200
    assert_error(await _check(client, staff), 409, "ATTENDANCE_ALREADY_CHECKED_IN")
    clock("12:10")
    assert (await _check(client, staff, action="check-out")).status_code == 200
    assert_error(
        await _check(client, staff, action="check-out"), 409, "ATTENDANCE_ALREADY_CHECKED_OUT"
    )
    # An absent record can't be checked out of.
    clock("12:31")
    await session.execute(
        update(AttendanceRecord).values(
            status="absent",
            check_in_at=None,
            checkout_status=None,
            check_out_at=None,
            late_minutes=0,
        )
    )
    await session.commit()
    assert_error(await _check(client, staff, action="check-out"), 409, "ATTENDANCE_NOT_CHECKED_IN")


async def test_location_rules(client, session, clock, workplace, staff) -> None:
    clock("07:00")
    r = await _check(client, staff, metres_north=320)
    assert_error(r, 422, "ATTENDANCE_TOO_FAR")
    assert r.json()["error"]["details"] == {"distance_m": 320, "radius_m": 100}
    # Just inside the radius: a rough GPS reading (±250 m) doesn't refuse it, it's only stored.
    r = await _check(client, staff, metres_north=99, accuracy_m=250)
    assert r.status_code == 200, r.text
    assert r.json()["record"]["check_in_accuracy_m"] == 250
    entries = list(
        await session.scalars(
            select(AuditLog)
            .where(AuditLog.action == "attendance.attempt_refused")
            .order_by(AuditLog.id)
        )
    )
    assert [e.details["code"] for e in entries] == ["ATTENDANCE_TOO_FAR"]
    assert entries[0].details["distance_m"] == 320


async def test_window_checked_before_location(client, clock, workplace, staff) -> None:
    clock("06:00")
    assert_error(await _check(client, staff, metres_north=5000), 409, "ATTENDANCE_TOO_EARLY")


async def test_workplace_without_coordinates(client, clock, staff) -> None:
    clock("07:00")
    assert_error(await _check(client, staff), 409, "ATTENDANCE_WORKPLACE_NOT_SET")


async def test_not_tracked(client, clock, workplace, make_user, superadmin) -> None:
    clock("07:00")
    gm = await make_user(Role.GENERAL_MANAGER)
    for user in (gm, superadmin):
        assert_error(await _check(client, user), 403, "ATTENDANCE_NOT_REQUIRED")
        r = await client.get("/attendance/me/today", headers=auth(user))
        assert_error(r, 403, "ATTENDANCE_NOT_REQUIRED")


async def test_supervisors_are_tracked(client, clock, workplace, make_user) -> None:
    clock("07:00")
    sup = await make_user(Role.SUPERVISOR)
    assert (await _check(client, sup)).status_code == 200


async def test_snapshot_kept_after_time_change(client, session, clock, workplace, staff) -> None:
    clock("07:05")
    await _check(client, staff)
    await set_schedule(session, workplace, shift_times={"morning": ("08:00", "12:00")})
    clock("09:00")
    me = (await client.get("/attendance/me/today", headers=auth(staff))).json()
    morning = next(s for s in me["shifts"] if s["code"] == "morning")
    assert morning["start"].startswith("2026-10-13T08:00:00+07:00")  # the new time
    rec = morning["record"]
    assert rec["scheduled_start"].startswith("2026-10-13T07:00:00+07:00")  # the snapshot
    assert (rec["status"], rec["late_minutes"]) == ("late", 5)


async def test_me_today(client, clock, workplace, staff) -> None:
    clock("06:40")
    me = (await client.get("/attendance/me/today", headers=auth(staff))).json()
    assert me["timezone"] == "Asia/Phnom_Penh"
    assert me["work_date"] == "2026-10-13"
    assert me["server_time"].startswith("2026-10-13T06:40:00+07:00")
    assert me["workplace"]["has_coordinates"] is True
    assert me["workplace"]["radius_m"] == 100
    assert "max_accuracy_m" not in me
    assert [s["code"] for s in me["shifts"]] == ["morning", "afternoon"]
    assert [s["phase"] for s in me["shifts"]] == ["check_in_open", "upcoming"]
    assert me["shifts"][0]["check_in_until"].startswith("2026-10-13T07:44:00+07:00")
    na = me["next_action"]
    assert (na["action"], na["shift_code"]) == ("check_in", "morning")
    assert na["until"].startswith("2026-10-13T07:44:00+07:00")
    assert na["closes_at"].startswith("2026-10-13T07:45:00+07:00")

    clock("05:00")
    na = (await client.get("/attendance/me/today", headers=auth(staff))).json()["next_action"]
    assert (na["action"], na["next_action"], na["next_shift_code"]) == (
        "none",
        "check_in",
        "morning",
    )
    assert na["next_opens_at"].startswith("2026-10-13T06:30:00+07:00")


async def test_overlap_check_out_first(client, clock, workplace, staff) -> None:
    clock("07:00")
    await _check(client, staff)
    clock("12:40")
    na = (await client.get("/attendance/me/today", headers=auth(staff))).json()["next_action"]
    assert (na["action"], na["shift_code"]) == ("check_out", "morning")
    # Checking in now still picks the afternoon (the server decides by the window).
    r = await _check(client, staff, action="check-out")
    assert r.json()["today"]["next_action"]["action"] == "check_in"
    rec = (await _check(client, staff)).json()["record"]
    assert (rec["shift_code"], rec["status"]) == ("afternoon", "present")


async def test_confirmation_message(client, session, clock, workplace, staff, telegram_bot):
    """A confirmation in the user's language after the commit, with the check-screen button."""
    clock("07:12")
    await _check(client, staff)
    (sent,) = telegram_bot.calls("SendMessage")
    assert sent.chat_id == 5001
    assert sent.text == "✅ បានចុះវត្តមាន — វេនព្រឹក ម៉ោង 07:12 (មកយឺត 12 នាទី)"
    button = sent.reply_markup.inline_keyboard[0][0]
    assert button.web_app.url == "https://app.example.com/attendance/check"

    await session.execute(update(User).where(User.id == staff.id).values(language="en"))
    await session.commit()
    clock("12:03")
    await _check(client, staff, action="check-out")
    sent = telegram_bot.calls("SendMessage")[-1]
    assert sent.text == "👋 Checked out — morning shift, 12:03 (+3 min overtime)"


async def test_confirmation_mentions_early_check_in(
    client, session, clock, workplace, staff, telegram_bot
) -> None:
    clock(at("06:40:30"))
    await _check(client, staff)
    (sent,) = telegram_bot.calls("SendMessage")
    assert sent.text == "✅ បានចុះវត្តមាន — វេនព្រឹក ម៉ោង 06:40 (មកមុន 20 នាទី)"


async def test_no_confirmation_without_bot(client, clock, workplace, staff) -> None:
    clock("07:00")
    assert (await _check(client, staff)).status_code == 200  # nothing raised


async def test_check_in_at_exact_times(client, clock, workplace, staff) -> None:
    clock(at("07:00:59"))
    rec = (await _check(client, staff)).json()["record"]
    assert (rec["status"], rec["late_minutes"]) == ("present", 0)
