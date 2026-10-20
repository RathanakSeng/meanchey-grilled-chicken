"""Attendance start date and optional tracking for supervisors (app/attendance/tracking.py):
create / edit / role change rules, who is tracked on a date in the scheduler, check-in,
`me/today`, the bot's /start gating, the day view and the summaries, and the untracked periods."""

import asyncio
from datetime import date

from alembic import command
from sqlalchemy import select, update

from app.attendance import scheduler
from app.bot.handlers import _is_tracked
from app.models import (
    AttendanceRecord,
    AttendanceReminder,
    AttendanceUntrackedPeriod,
    AuditLog,
    Role,
    User,
)
from tests.conftest import assert_error, at, auth, position
from tests.test_migration_step_dates import _alembic, _run

TODAY = "2026-10-13"  # the `clock` fixture's day


def _staff_body(username: str, **extra) -> dict:
    return {
        "role": "staff",
        "full_name": "Dara",
        "telegram_username": username,
        "position": "Cook",
        **extra,
    }


def _sup_body(username: str, **extra) -> dict:
    return {"role": "supervisor", "full_name": "Sok", "telegram_username": username, **extra}


async def _fresh(session, user_id) -> User:
    return await session.scalar(
        select(User).where(User.id == user_id).execution_options(populate_existing=True)
    )


async def _periods(session, user_id) -> list[tuple[date, date | None]]:
    rows = await session.execute(
        select(AttendanceUntrackedPeriod.from_date, AttendanceUntrackedPeriod.to_date)
        .where(AttendanceUntrackedPeriod.user_id == user_id)
        .order_by(AttendanceUntrackedPeriod.from_date)
    )
    return [tuple(r) for r in rows]


async def _records_of(session, user_id) -> list[AttendanceRecord]:
    return list(
        await session.scalars(
            select(AttendanceRecord)
            .where(AttendanceRecord.user_id == user_id)
            .order_by(AttendanceRecord.scheduled_start)
            .execution_options(populate_existing=True)
        )
    )


async def _backdate(session, *users, hm="05:00", day=TODAY) -> None:
    await session.execute(
        update(User).where(User.id.in_([u.id for u in users])).values(created_at=at(hm, day))
    )
    await session.commit()


# --- Start date ----------------------------------------------------------------------------------


async def test_create_defaults_to_today_or_a_future_date(client, clock, superadmin) -> None:
    clock("09:00")
    h = auth(superadmin)
    r = await client.post("/users", json=_staff_body("start_default"), headers=h)
    assert r.status_code == 201, r.text
    assert (r.json()["attendance_start_date"], r.json()["attendance_tracked"]) == (TODAY, True)
    r = await client.post(
        "/users", json=_sup_body("start_future", attendance_start_date="2026-10-20"), headers=h
    )
    assert r.status_code == 201 and r.json()["attendance_start_date"] == "2026-10-20"
    r = await client.post(
        "/users", json=_staff_body("start_today", attendance_start_date=TODAY), headers=h
    )
    assert r.status_code == 201


async def test_create_in_the_past_is_refused(client, clock, superadmin) -> None:
    clock("09:00")
    r = await client.post(
        "/users",
        json=_staff_body("start_past", attendance_start_date="2026-10-12"),
        headers=auth(superadmin),
    )
    assert_error(r, 422, "VALIDATION_ERROR")
    assert r.json()["error"]["details"]["code"] == "ATTENDANCE_START_IN_PAST"


async def test_general_manager_has_no_start_date(client, clock, superadmin) -> None:
    clock("09:00")
    h = auth(superadmin)
    body = {"role": "general_manager", "full_name": "Boss", "telegram_username": "gm_start"}
    r = await client.post("/users", json=body, headers=h)
    assert r.status_code == 201 and r.json()["attendance_start_date"] is None
    r = await client.post(
        "/users",
        json={**body, "telegram_username": "gm_start2", "attendance_start_date": TODAY},
        headers=h,
    )
    assert_error(r, 422, "VALIDATION_ERROR")


async def test_edit_only_while_in_the_future(client, clock, superadmin) -> None:
    clock("09:00")
    h = auth(superadmin)
    r = await client.post(
        "/users", json=_staff_body("edit_start", attendance_start_date="2026-10-20"), headers=h
    )
    uid = r.json()["id"]
    r = await client.patch(f"/users/{uid}", json={"attendance_start_date": "2026-10-22"}, headers=h)
    assert r.status_code == 200 and r.json()["attendance_start_date"] == "2026-10-22"
    r = await client.patch(f"/users/{uid}", json={"attendance_start_date": "2026-10-12"}, headers=h)
    assert_error(r, 422, "VALIDATION_ERROR")
    assert r.json()["error"]["details"]["code"] == "ATTENDANCE_START_IN_PAST"
    # The date arrives: read-only (the same value is still accepted).
    clock(at("08:00", "2026-10-22"))
    r = await client.patch(f"/users/{uid}", json={"attendance_start_date": "2026-10-25"}, headers=h)
    assert_error(r, 409, "ATTENDANCE_START_LOCKED")
    r = await client.patch(f"/users/{uid}", json={"attendance_start_date": "2026-10-22"}, headers=h)
    assert r.status_code == 200
    # Started today at creation: locked straight away.
    clock("09:00")
    created = await client.post("/users", json=_staff_body("edit_started"), headers=h)
    r = await client.patch(
        f"/users/{created.json()['id']}", json={"attendance_start_date": "2026-10-20"}, headers=h
    )
    assert_error(r, 409, "ATTENDANCE_START_LOCKED")


async def test_role_change_sets_and_clears_the_start_date(client, clock, superadmin) -> None:
    clock("09:00")
    h = auth(superadmin)
    gm = (
        await client.post(
            "/users",
            json={"role": "general_manager", "full_name": "G", "telegram_username": "rc_gm"},
            headers=h,
        )
    ).json()
    url = f"/users/{gm['id']}/role"
    r = await client.post(url, json={"role": "supervisor"}, headers=h)
    assert r.status_code == 200 and r.json()["attendance_start_date"] == TODAY
    r = await client.post(url, json={"role": "general_manager"}, headers=h)
    assert r.json()["attendance_start_date"] is None
    r = await client.post(
        url,
        json={"role": "staff", "position": "Cook", "attendance_start_date": "2026-10-30"},
        headers=h,
    )
    assert r.status_code == 200 and r.json()["attendance_start_date"] == "2026-10-30"
    # Staff -> supervisor keeps the date.
    r = await client.post(url, json={"role": "supervisor"}, headers=h)
    assert r.json()["attendance_start_date"] == "2026-10-30"
    # A past date into staff / supervisor, or a date for a general manager: refused.
    await client.post(url, json={"role": "general_manager"}, headers=h)
    r = await client.post(
        url, json={"role": "supervisor", "attendance_start_date": "2026-10-01"}, headers=h
    )
    assert_error(r, 422, "VALIDATION_ERROR")
    r = await client.post(
        url, json={"role": "general_manager", "attendance_start_date": TODAY}, headers=h
    )
    assert r.status_code == 200  # same role: a no-op
    await client.post(url, json={"role": "supervisor"}, headers=h)
    r = await client.post(
        url, json={"role": "general_manager", "attendance_start_date": TODAY}, headers=h
    )
    assert_error(r, 422, "VALIDATION_ERROR")


# --- Before the start date -----------------------------------------------------------------------


async def test_before_the_start_date_nothing_is_tracked(
    client, session, clock, workplace, superadmin
) -> None:
    clock("06:00")
    h = auth(superadmin)
    r = await client.post(
        "/users", json=_staff_body("later_staff", attendance_start_date="2026-10-14"), headers=h
    )
    staff = await _fresh(session, r.json()["id"])
    await _backdate(session, staff, hm="05:00")
    await session.execute(
        update(User)
        .where(User.id == staff.id)
        .values(telegram_user_id=7001, must_change_password=False)
    )
    await session.commit()
    headers = auth(staff)

    # me/today: nothing to do, with the start date.
    clock("06:50")
    resp = await client.get("/attendance/me/today", headers=headers)
    assert resp.status_code == 200, resp.text
    today = resp.json()
    assert today["next_action"]["action"] == "none" and today["shifts"] == []
    assert (today["tracked"], today["starts_on"]) == (True, "2026-10-14")
    # Check-in refused with the start date.
    r = await client.post("/attendance/check-in", json=position(), headers=headers)
    assert_error(r, 409, "ATTENDANCE_NOT_STARTED")
    assert r.json()["error"]["details"]["start_date"] == "2026-10-14"
    # Scheduler: no reminder, no absent.
    result = await scheduler.run_tick(at("06:50"))
    assert result is not None and result.reminders == []
    await scheduler.run_tick(at("07:45"))
    assert list(await session.scalars(select(AttendanceRecord.id))) == []
    assert list(await session.scalars(select(AttendanceReminder.id))) == []
    # The bot still offers Attendance (it starts later).
    assert await _is_tracked(7001) is True
    # Day view: not expected, in the "Starts later" group.
    day = (await client.get(f"/attendance/day?date={TODAY}", headers=h)).json()
    assert day["rows"] == []
    assert [(row["user"]["id"], row["starts_on"]) for row in day["starts_later"]] == [
        (str(staff.id), "2026-10-14")
    ]
    assert all(s["kpis"]["expected"] == 0 for s in day["shifts"])
    # Summary: no days before the start date.
    summary = (await client.get("/attendance/me/summary", headers=headers)).json()
    assert summary["days"] == [] and summary["employee"]["since"] == "2026-10-14"

    # From the start date everything works.
    clock(at("07:00", "2026-10-14"))
    today = (await client.get("/attendance/me/today", headers=headers)).json()
    assert today["next_action"]["action"] == "check_in" and today["starts_on"] is None
    r = await client.post("/attendance/check-in", json=position(), headers=headers)
    assert r.status_code == 200, r.text
    day = (await client.get("/attendance/day?date=2026-10-14", headers=h)).json()
    assert [row["user"]["id"] for row in day["rows"]] == [str(staff.id)]
    assert day["starts_later"] == []


# --- Tracking toggle -----------------------------------------------------------------------------


async def test_only_supervisors_can_be_switched_off(client, clock, make_user) -> None:
    clock("09:00")
    gm = await make_user(Role.GENERAL_MANAGER)
    staff = await make_user(Role.STAFF)
    sup = await make_user(Role.SUPERVISOR)
    editor = await make_user(Role.SUPERVISOR, perms=["users.view", "users.update"])
    h = auth(gm)
    # Staff are always tracked: "on" is a no-op, "off" is refused.
    r = await client.patch(f"/users/{staff.id}", json={"attendance_tracked": True}, headers=h)
    assert r.status_code == 200 and r.json()["attendance_tracked"] is True
    r = await client.patch(f"/users/{staff.id}", json={"attendance_tracked": False}, headers=h)
    assert_error(r, 422, "VALIDATION_ERROR")
    # A supervisor can't change it for another supervisor or for themselves.
    for target in (sup, editor):
        r = await client.patch(
            f"/users/{target.id}", json={"attendance_tracked": False}, headers=auth(editor)
        )
        assert r.status_code in (403, 404), r.text
    # A GM can for a supervisor, not for another GM.
    r = await client.patch(f"/users/{sup.id}", json={"attendance_tracked": False}, headers=h)
    assert r.status_code == 200, r.text
    assert (r.json()["attendance_tracked"], r.json()["attendance_untracked_since"]) == (
        False,
        TODAY,
    )
    other_gm = await make_user(Role.GENERAL_MANAGER)
    r = await client.patch(f"/users/{other_gm.id}", json={"attendance_tracked": False}, headers=h)
    assert r.status_code == 403


async def test_off_today_keeps_records_and_stops_later_windows(
    client, session, clock, workplace, make_user
) -> None:
    sup = await make_user(Role.SUPERVISOR, telegram_user_id=7002)
    other = await make_user(Role.SUPERVISOR)
    gm = await make_user(Role.GENERAL_MANAGER)
    await _backdate(session, sup, other)
    clock("07:00")
    r = await client.post("/attendance/check-in", json=position(), headers=auth(sup))
    assert r.status_code == 200, r.text

    clock("09:00")
    r = await client.patch(f"/users/{sup.id}", json={"attendance_tracked": False}, headers=auth(gm))
    assert r.status_code == 200
    assert await _periods(session, sup.id) == [(date(2026, 10, 13), None)]
    audit = await session.scalar(
        select(AuditLog).where(AuditLog.action == "user.update", AuditLog.target_user_id == sup.id)
    )
    assert audit.details["changes"]["attendance_tracked"] == [True, False]

    # The record made today is kept: no forgot check-out, no later absent, no reminders.
    result = await scheduler.run_tick(at("12:00"))
    assert result is not None and result.reminders == []
    result = await scheduler.run_tick(at("13:00"))
    assert result.forgot_checkout == 0
    await scheduler.run_tick(at("13:45"))
    assert [
        (r.shift_code, r.status, r.checkout_status) for r in await _records_of(session, sup.id)
    ] == [("morning", "present", None)]
    # The other (tracked) supervisor still gets absent marks.
    assert [r.shift_code for r in await _records_of(session, other.id)] == [
        "morning",
        "afternoon",
    ]

    # Check-out refused, me/today says so, no Attendance button.
    clock("12:40")
    r = await client.post("/attendance/check-out", json=position(), headers=auth(sup))
    assert_error(r, 403, "ATTENDANCE_NOT_REQUIRED")
    today = (await client.get("/attendance/me/today", headers=auth(sup))).json()
    assert (today["tracked"], today["next_action"]["action"]) == (False, "none")
    assert await _is_tracked(7002) is False

    # Day view: not expected, in "Not tracked", with the kept record.
    day = (await client.get(f"/attendance/day?date={TODAY}", headers=auth(gm))).json()
    assert str(sup.id) not in [row["user"]["id"] for row in day["rows"]]
    (row,) = day["not_tracked"]
    assert row["user"]["id"] == str(sup.id) and row["shifts"]["morning"]["state"] == "recorded"
    morning = next(s for s in day["shifts"] if s["code"] == "morning")
    assert morning["kpis"]["expected"] == 1  # only the other supervisor

    # My attendance stays available; today is "Not tracked" and counts nowhere.
    summary = (await client.get("/attendance/me/summary", headers=auth(sup))).json()
    assert summary["days"][0]["not_tracked"] is True
    assert summary["kpis"]["present"]["total_shifts"] == 0
    manager = (await client.get(f"/attendance/users/{sup.id}/summary", headers=auth(gm))).json()
    assert manager["days"][0]["not_tracked"] is True


async def test_pending_reminders_are_skipped_once_switched_off(
    client, session, clock, workplace, make_user
) -> None:
    sup = await make_user(Role.SUPERVISOR, telegram_user_id=7003)
    gm = await make_user(Role.GENERAL_MANAGER)
    await _backdate(session, sup)
    session.add(
        AttendanceReminder(
            user_id=sup.id,
            work_date=date(2026, 10, 13),
            shift_code="morning",
            kind="check_in",
            window_closes_at=at("07:45"),
        )
    )
    await session.commit()
    clock("06:40")
    await client.patch(f"/users/{sup.id}", json={"attendance_tracked": False}, headers=auth(gm))
    result = await scheduler.run_tick(at("06:40"))
    assert result is not None and result.reminders == [] and result.skipped == 1


async def test_on_again_resumes_from_today(client, session, clock, workplace, make_user) -> None:
    sup = await make_user(Role.SUPERVISOR)
    gm = await make_user(Role.GENERAL_MANAGER)
    await _backdate(session, sup)
    h = auth(gm)
    clock("09:00")
    await client.patch(f"/users/{sup.id}", json={"attendance_tracked": False}, headers=h)
    # Switched back on the same day: the period (started today) is removed.
    r = await client.patch(f"/users/{sup.id}", json={"attendance_tracked": True}, headers=h)
    assert r.status_code == 200 and r.json()["attendance_untracked_since"] is None
    assert await _periods(session, sup.id) == []
    # Off again, then on three days later: the period is closed at yesterday.
    await client.patch(f"/users/{sup.id}", json={"attendance_tracked": False}, headers=h)
    clock(at("09:00", "2026-10-16"))
    r = await client.patch(f"/users/{sup.id}", json={"attendance_tracked": True}, headers=h)
    assert r.json()["attendance_tracked"] is True
    assert await _periods(session, sup.id) == [(date(2026, 10, 13), date(2026, 10, 15))]
    # Tracking resumes from today: check-in works, the days in between are "Not tracked".
    clock(at("07:10", "2026-10-16"))
    r = await client.post("/attendance/check-in", json=position(), headers=auth(sup))
    assert r.status_code == 200, r.text
    summary = (await client.get("/attendance/me/summary", headers=auth(sup))).json()
    flags = {d["date"]: d["not_tracked"] for d in summary["days"]}
    assert flags["2026-10-16"] is False
    assert flags["2026-10-15"] is flags["2026-10-14"] is flags["2026-10-13"] is True
    # A second switch-off starts a second period.
    await client.patch(f"/users/{sup.id}", json={"attendance_tracked": False}, headers=h)
    assert len(await _periods(session, sup.id)) == 2


async def test_role_change_closes_periods(client, session, clock, superadmin) -> None:
    clock("09:00")
    h = auth(superadmin)
    created = await client.post("/users", json=_sup_body("rc_untracked"), headers=h)
    uid = created.json()["id"]
    await client.patch(f"/users/{uid}", json={"attendance_tracked": False}, headers=h)
    clock(at("09:00", "2026-10-15"))
    r = await client.post(
        f"/users/{uid}/role", json={"role": "staff", "position": "Cook"}, headers=h
    )
    assert r.status_code == 200
    assert (r.json()["attendance_tracked"], r.json()["attendance_untracked_since"]) == (True, None)
    assert await _periods(session, uid) == [(date(2026, 10, 13), date(2026, 10, 14))]
    # Staff -> supervisor keeps tracking on.
    r = await client.post(f"/users/{uid}/role", json={"role": "supervisor"}, headers=h)
    assert r.json()["attendance_tracked"] is True
    # Switched off (today), then to GM: the period started today, so it is removed.
    await client.patch(f"/users/{uid}", json={"attendance_tracked": False}, headers=h)
    r = await client.post(f"/users/{uid}/role", json={"role": "general_manager"}, headers=h)
    assert r.json()["attendance_start_date"] is None and r.json()["attendance_tracked"] is True
    assert await _periods(session, uid) == [(date(2026, 10, 13), date(2026, 10, 14))]


async def test_untracked_summary_days_are_excluded_from_kpis(
    client, session, clock, workplace, make_user
) -> None:
    sup = await make_user(Role.SUPERVISOR)
    gm = await make_user(Role.GENERAL_MANAGER)
    await _backdate(session, sup, day="2026-10-01")
    session.add_all(
        [
            AttendanceRecord(
                user_id=sup.id,
                work_date=date.fromisoformat(day),
                shift_code="morning",
                workplace_id=workplace.id,
                scheduled_start=at("07:00", day),
                scheduled_end=at("12:00", day),
                status="absent",
                late_minutes=0,
                source="auto",
            )
            for day in ("2026-10-05", "2026-10-06", "2026-10-07")
        ]
        + [
            AttendanceUntrackedPeriod(
                user_id=sup.id, from_date=date(2026, 10, 6), to_date=date(2026, 10, 10)
            )
        ]
    )
    await session.commit()
    clock("09:00")
    summary = (await client.get(f"/attendance/users/{sup.id}/summary", headers=auth(gm))).json()
    assert summary["kpis"]["absent"]["total_shifts"] == 1  # 5 Oct only
    untracked = [d["date"] for d in summary["days"] if d["not_tracked"]]
    assert untracked == [f"2026-10-{d:02d}" for d in (10, 9, 8, 7, 6)]


# --- Migration -----------------------------------------------------------------------------------


def test_backfill_uses_the_creation_date_in_business_time() -> None:
    _alembic(command.downgrade, "0020")
    try:
        asyncio.run(
            _run(
                "INSERT INTO users (id, role, position, full_name, telegram_username, "
                "password_hash, created_at) VALUES "
                # 05:00 on 1 October in Phnom Penh.
                "(gen_random_uuid(), 'staff', 'Cook', 'S', 'mig_start_s', 'x', "
                "TIMESTAMPTZ '2026-09-30 22:00+00'), "
                "(gen_random_uuid(), 'supervisor', NULL, 'V', 'mig_start_v', 'x', "
                "TIMESTAMPTZ '2026-09-30 10:00+00'), "
                "(gen_random_uuid(), 'general_manager', NULL, 'G', 'mig_start_g', 'x', "
                "TIMESTAMPTZ '2026-09-30 10:00+00')"
            )
        )
    finally:
        _alembic(command.upgrade, "head")
    rows = asyncio.run(
        _run(
            "SELECT telegram_username, attendance_start_date::text, attendance_tracked "
            "FROM users WHERE telegram_username LIKE 'mig_start_%' ORDER BY telegram_username"
        )
    )
    assert rows == [
        ("mig_start_g", None, True),
        ("mig_start_s", "2026-10-01", True),
        ("mig_start_v", "2026-09-30", True),
    ]
