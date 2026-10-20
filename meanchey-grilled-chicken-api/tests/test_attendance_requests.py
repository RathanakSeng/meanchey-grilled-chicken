"""Attendance requests: a month's missing time covered by a salary cut and / or unpaid extra work.

Eligibility (at least an hour), the window (1st of the next month to the deadline day), one
request per month, the split rule and the type, the snapshot, the month lock (corrections,
added records, holidays), the review (approve, approve with changes, reject), scope, the
`no_request` listing, the deadline setting, notifications and the 1st-of-month reminder,
summaries and permissions."""

from datetime import date

import pytest
from sqlalchemy import select, update

from app.attendance import requests as req
from app.attendance import scheduler
from app.main import app
from app.models import (
    AttendanceRecord,
    AttendanceRequest,
    AuditLog,
    Notification,
    Role,
    User,
)
from app.permissions.registry import DEFAULT_PERMISSIONS
from tests.conftest import assert_error, at, auth

REVIEW = "attendance.requests_review"
OCTOBER_MISSING = 405  # 6 h 45: absent morning (300) + late afternoon (105)


def _record(user, workplace, day: str, shift: str, status: str, **kw) -> AttendanceRecord:
    start, end = ("07:00", "12:00") if shift == "morning" else ("13:00", "15:00")
    return AttendanceRecord(
        user_id=user.id,
        work_date=date.fromisoformat(day),
        shift_code=shift,
        workplace_id=workplace.id,
        scheduled_start=at(start, day),
        scheduled_end=at(end, day),
        status=status,
        check_in_at=None if status == "absent" else at(start, day),
        source="mini_app",
        **kw,
    )


async def _backdate(session, *users) -> None:
    await session.execute(
        update(User)
        .where(User.id.in_([u.id for u in users]))
        .values(created_at=at("10:00", "2026-09-01"))
    )
    await session.commit()


async def _english(session, *users) -> None:
    await session.execute(
        update(User).where(User.id.in_([u.id for u in users])).values(language="en")
    )
    await session.commit()


async def _october(session, workplace, user, *, absent: bool = True, late: int = 105):
    """October 2026: -405 min by default (absent morning 300 + late afternoon 105)."""
    session.add_all(
        [
            _record(user, workplace, "2026-10-02", "morning", "absent" if absent else "present"),
            _record(user, workplace, "2026-10-02", "afternoon", "late", late_minutes=late),
        ]
    )
    await session.commit()


@pytest.fixture
async def staff(session, workplace, make_user):
    user = await make_user(Role.STAFF, telegram_user_id=7001)
    await _backdate(session, user)
    await _october(session, workplace, user)
    return user


@pytest.fixture
async def gm(make_user):
    return await make_user(Role.GENERAL_MANAGER, telegram_user_id=7100)


def _body(cut: int = 120, work: int = 285, **extra) -> dict:
    return {
        "year": 2026,
        "month": 10,
        "salary_cut_minutes": cut,
        "unpaid_work_minutes": work,
        **extra,
    }


async def _submit(client, user, **kw):
    return await client.post("/attendance/requests", json=_body(**kw), headers=auth(user))


async def _rows(session) -> list[AttendanceRequest]:
    return list(
        await session.scalars(select(AttendanceRequest).execution_options(populate_existing=True))
    )


# --- Rules ---------------------------------------------------------------------------------------


def test_pure_rules() -> None:
    w = req.window(2026, 10, 7)
    assert (w.opens, w.closes) == (date(2026, 11, 1), date(2026, 11, 7))
    assert req.window(2026, 12, 7).opens == date(2027, 1, 1)
    assert req.missing_minutes(-405) == 405 and req.missing_minutes(30) == 0
    today = date(2026, 11, 3)
    assert req.eligibility(2026, 10, -405, 7, today) == "eligible"
    assert req.eligibility(2026, 10, -59, 7, today) == "not_needed"
    assert req.eligibility(2026, 10, -60, 7, today) == "eligible"
    assert req.eligibility(2026, 11, -405, 7, today) == "window_not_open"
    assert req.eligibility(2026, 10, -405, 7, date(2026, 11, 8)) == "window_closed"
    assert req.eligibility(2026, 10, -405, 7, date(2026, 11, 7)) == "eligible"
    assert [req.request_type(1, 0), req.request_type(0, 1), req.request_type(1, 1)] == [
        "salary_cut",
        "unpaid_work",
        "both",
    ]


async def test_months_eligibility_and_window(client, clock, staff) -> None:
    h = auth(staff)

    async def october(now: str, day: str = "2026-11-03") -> dict:
        clock(at(now, day))
        r = await client.get("/attendance/requests/me?year=2026", headers=h)
        assert r.status_code == 200, r.text
        return next(m for m in r.json()["months"] if m["month"] == 10), r.json()

    row, body = await october("09:00", "2026-10-31")
    assert row["eligibility"] == "window_not_open" and row["opens"] == "2026-11-01"
    row, body = await october("09:00")
    assert (row["eligibility"], row["missing_minutes"], row["balance_minutes"]) == (
        "eligible",
        OCTOBER_MISSING,
        -OCTOBER_MISSING,
    )
    assert (row["absent_minutes"], row["late_minutes"], row["closes"]) == (300, 105, "2026-11-07")
    assert body["request_deadline_day"] == 7
    # September has no records: nothing to cover. Newest first, up to the current month.
    assert [m["month"] for m in body["months"]][:2] == [11, 10]
    sept = next(m for m in body["months"] if m["month"] == 9)
    assert sept["eligibility"] == "not_needed"
    row, _ = await october("09:00", "2026-11-08")
    assert row["eligibility"] == "window_closed" and row["request"] is None


async def test_submit_rules(client, session, clock, staff, gm) -> None:
    clock(at("09:00", "2026-11-03"))
    # Current / future month: the window is not open.
    for month in (11, 12):
        r = await _submit(client, staff, month=month)
        assert_error(r, 409, "ATTENDANCE_REQUEST_WINDOW_CLOSED")
    r = await _submit(client, staff, month=11)
    assert r.json()["error"]["details"] == {"opens": "2026-12-01", "closes": "2026-12-07"}
    # September: its window is over; and inside the window an hour is needed.
    assert_error(await _submit(client, staff, month=9), 409, "ATTENDANCE_REQUEST_WINDOW_CLOSED")
    clock(at("09:00", "2026-10-03"))
    assert_error(await _submit(client, staff, month=9), 409, "ATTENDANCE_REQUEST_NOT_NEEDED")
    # Split must add up exactly.
    clock(at("09:00", "2026-11-03"))
    bad = await _submit(client, staff, cut=100, work=200)
    assert_error(bad, 422, "ATTENDANCE_REQUEST_SPLIT_MISMATCH")
    assert bad.json()["error"]["details"] == {"expected": 405, "given": 300}
    # Negative values are refused by validation.
    assert_error(await _submit(client, staff, cut=-5, work=410), 422, "VALIDATION_ERROR")
    assert await _rows(session) == []
    r = await _submit(client, staff, note="  Sorry  ")
    assert r.status_code == 201, r.text
    body = r.json()
    assert (body["status"], body["type"], body["note"]) == ("pending", "both", "Sorry")
    assert (body["missing_minutes"], body["balance_minutes"], body["month_locked"]) == (
        405,
        -405,
        True,
    )
    assert (body["absent_minutes"], body["late_minutes"], body["extra_minutes"]) == (300, 105, 0)
    assert body["approved_salary_cut_minutes"] is None
    # One per month; the employee can't edit or withdraw it.
    assert_error(await _submit(client, staff), 409, "ATTENDANCE_REQUEST_EXISTS")
    for method in ("patch", "put", "delete"):
        r = await getattr(client, method)(f"/attendance/requests/{body['id']}", headers=auth(staff))
        assert r.status_code == 405
    audit = await session.scalar(
        select(AuditLog).where(AuditLog.action == "attendance.request_submit")
    )
    assert audit.details["salary_cut_minutes"] == 120 and audit.actor_id == staff.id


async def test_type_is_derived_from_the_split(client, clock, staff) -> None:
    clock(at("09:00", "2026-11-03"))
    r = await _submit(client, staff, cut=0, work=405)
    assert (r.status_code, r.json()["type"]) == (201, "unpaid_work")


async def test_under_an_hour_needs_no_request(client, session, clock, workplace, make_user) -> None:
    clock(at("09:00", "2026-11-03"))
    worker = await make_user(Role.STAFF)
    await _backdate(session, worker)
    await _october(session, workplace, worker, absent=False, late=30)  # 30 min missing
    assert_error(
        await _submit(client, worker, cut=0, work=30), 409, "ATTENDANCE_REQUEST_NOT_NEEDED"
    )
    r = await client.get("/attendance/requests/me?year=2026", headers=auth(worker))
    assert next(m for m in r.json()["months"] if m["month"] == 10)["eligibility"] == "not_needed"
    # Extra time counts against the missing time: 120 - 70 = 50 min is under an hour too.
    session.add(_record(worker, workplace, "2026-10-05", "morning", "present", overtime_minutes=70))
    await session.commit()
    r = await client.get("/attendance/requests/me?year=2026", headers=auth(worker))
    october = next(m for m in r.json()["months"] if m["month"] == 10)
    assert (october["balance_minutes"], october["extra_minutes"]) == (40, 70)


async def test_no_request_for_untracked_roles(client, clock, gm) -> None:
    clock(at("09:00", "2026-11-03"))
    assert_error(
        await client.get("/attendance/requests/me", headers=auth(gm)),
        403,
        "ATTENDANCE_NOT_REQUIRED",
    )
    assert_error(await _submit(client, gm), 403, "ATTENDANCE_NOT_REQUIRED")


async def test_deadline_closes_the_window(client, clock, staff) -> None:
    clock(at("23:00", "2026-11-07"))
    r = await _submit(client, staff)
    assert r.status_code == 201, r.text


async def test_after_the_deadline_refused(client, clock, staff) -> None:
    clock(at("00:00", "2026-11-08"))
    r = await _submit(client, staff)
    assert_error(r, 409, "ATTENDANCE_REQUEST_WINDOW_CLOSED")
    assert r.json()["error"]["details"]["closes"] == "2026-11-07"


# --- Snapshot and month lock ---------------------------------------------------------------------


async def _first_record(session, user) -> AttendanceRecord:
    return await session.scalar(
        select(AttendanceRecord)
        .where(AttendanceRecord.user_id == user.id, AttendanceRecord.shift_code == "morning")
        .execution_options(populate_existing=True)
    )


async def test_month_lock_and_snapshot(client, session, clock, workplace, staff, gm) -> None:
    clock(at("09:00", "2026-11-03"))
    record = await _first_record(session, staff)
    fix = {"status": "present", "check_in_time": "07:00", "reason": "Was at work"}
    add = {
        "user_id": str(staff.id),
        "work_date": "2026-10-09",
        "shift_code": "morning",
        "status": "present",
        "check_in_time": "07:00",
        "reason": "Paper sheet",
    }
    request = (await _submit(client, staff)).json()
    # Pending: no fix, no added record in October; November is free.
    assert_error(
        await client.patch(f"/attendance/records/{record.id}", json=fix, headers=auth(gm)),
        409,
        "ATTENDANCE_MONTH_LOCKED",
    )
    r = await client.post("/attendance/records", json=add, headers=auth(gm))
    assert_error(r, 409, "ATTENDANCE_MONTH_LOCKED")
    assert r.json()["error"]["details"] == {"year": 2026, "month": 10}
    # Approved: still locked.
    await client.post(f"/attendance/requests/{request['id']}/approve", json={}, headers=auth(gm))
    assert_error(
        await client.patch(f"/attendance/records/{record.id}", json=fix, headers=auth(gm)),
        409,
        "ATTENDANCE_MONTH_LOCKED",
    )
    # The summary reports the request and the lock.
    s = (await client.get("/attendance/me/summary?year=2026&month=10", headers=auth(staff))).json()
    assert s["month_locked"] is True and s["request_eligibility"] == "eligible"
    assert (s["request"]["status"], s["request"]["approved_salary_cut_minutes"]) == (
        "approved",
        120,
    )
    manager = (
        await client.get(
            f"/attendance/users/{staff.id}/summary?year=2026&month=10", headers=auth(gm)
        )
    ).json()
    assert manager["month_locked"] is True and manager["request"]["id"] == request["id"]
    # A year has no request / lock.
    year = (await client.get("/attendance/me/summary?year=2026", headers=auth(staff))).json()
    assert (year["request"], year["month_locked"], year["request_eligibility"]) == (
        None,
        False,
        None,
    )


async def test_rejection_unlocks_and_snapshot_is_kept(client, session, clock, staff, gm) -> None:
    clock(at("09:00", "2026-11-03"))
    record = await _first_record(session, staff)
    request = (await _submit(client, staff)).json()
    r = await client.post(
        f"/attendance/requests/{request['id']}/reject",
        json={"reason": "Not agreed"},
        headers=auth(gm),
    )
    assert r.status_code == 200, r.text
    # Unlocked: the record can be fixed (absent → present) ...
    fix = {"status": "present", "check_in_time": "07:00", "reason": "Was at work"}
    r = await client.patch(f"/attendance/records/{record.id}", json=fix, headers=auth(gm))
    assert r.status_code == 200, r.text
    # ... and the request still shows the numbers of the day it was sent.
    shown = (await client.get(f"/attendance/requests/{request['id']}", headers=auth(staff))).json()
    assert (shown["missing_minutes"], shown["balance_minutes"], shown["absent_minutes"]) == (
        405,
        -405,
        300,
    )
    assert shown["month_locked"] is False
    s = (await client.get("/attendance/me/summary?year=2026&month=10", headers=auth(staff))).json()
    assert (s["month_locked"], s["request"]["status"]) == (False, "rejected")
    assert s["kpis"]["balance_minutes"] == -105  # the month has changed since
    # No new request for the month after a rejection.
    assert_error(await _submit(client, staff), 409, "ATTENDANCE_REQUEST_EXISTS")


async def test_holiday_skips_locked_months(
    client, session, clock, superadmin, workplace, staff, make_user, gm
) -> None:
    other = await make_user(Role.STAFF)
    await _backdate(session, other)
    await _october(session, workplace, other)
    clock(at("09:00", "2026-11-03"))
    request = (await _submit(client, staff)).json()
    body = {
        "name_km": "ថ្ងៃឈប់",
        "name_en": "Day off",
        "start_date": "2026-10-02",
        "end_date": "2026-10-02",
        "scope": "all",
    }
    r = await client.post("/attendance/holidays", json=body, headers=auth(superadmin))
    assert r.status_code == 201, r.text
    # The other employee lost the 2 records; the locked month's 2 are reported and kept.
    assert (r.json()["records_removed"], r.json()["skipped_locked"]) == (2, 2)
    kept = await session.scalars(
        select(AttendanceRecord)
        .where(AttendanceRecord.user_id == staff.id)
        .execution_options(populate_existing=True)
    )
    assert len(list(kept)) == 2
    # After a rejection the month is free for later changes (a second holiday day removes them).
    await client.post(
        f"/attendance/requests/{request['id']}/reject", json={"reason": "No"}, headers=auth(gm)
    )
    body.update(start_date="2026-10-02", end_date="2026-10-03", name_en="Longer")
    holiday_id = r.json()["holiday"]["id"]
    r = await client.patch(
        f"/attendance/holidays/{holiday_id}", json=body, headers=auth(superadmin)
    )
    assert r.status_code == 200, r.text
    assert r.json()["skipped_locked"] == 0


# --- Review --------------------------------------------------------------------------------------


async def test_approve_as_submitted(client, session, clock, staff, gm) -> None:
    clock(at("09:00", "2026-11-03"))
    request = (await _submit(client, staff)).json()
    r = await client.post(
        f"/attendance/requests/{request['id']}/approve", json={}, headers=auth(gm)
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["status"], body["approved_with_changes"]) == ("approved", False)
    assert (body["approved_salary_cut_minutes"], body["approved_unpaid_work_minutes"]) == (120, 285)
    assert (body["reviewed_by"]["id"], body["reviewed_at"] is not None) == (str(gm.id), True)
    audit = await session.scalar(
        select(AuditLog).where(AuditLog.action == "attendance.request_approve")
    )
    assert audit.details["with_changes"] is False and audit.actor_id == gm.id
    # Reviewed once.
    again = await client.post(
        f"/attendance/requests/{request['id']}/reject", json={"reason": "x"}, headers=auth(gm)
    )
    assert_error(again, 409, "ATTENDANCE_REQUEST_NOT_PENDING")


async def test_approve_with_changes(client, session, clock, staff, gm) -> None:
    clock(at("09:00", "2026-11-03"))
    request = (await _submit(client, staff)).json()
    url = f"/attendance/requests/{request['id']}/approve"
    bad = await client.post(
        url, json={"salary_cut_minutes": 100, "unpaid_work_minutes": 100}, headers=auth(gm)
    )
    assert_error(bad, 422, "ATTENDANCE_REQUEST_SPLIT_MISMATCH")
    assert bad.json()["error"]["details"] == {"expected": 405, "given": 200}
    over = await client.post(url, json={"salary_cut_minutes": 500}, headers=auth(gm))
    assert_error(over, 422, "ATTENDANCE_REQUEST_SPLIT_MISMATCH")
    r = await client.post(
        url,
        json={"salary_cut_minutes": 405, "unpaid_work_minutes": 0, "comment": "All salary cut"},
        headers=auth(gm),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["approved_with_changes"] is True and body["review_comment"] == "All salary cut"
    # Both splits are stored.
    assert (body["requested_salary_cut_minutes"], body["requested_unpaid_work_minutes"]) == (
        120,
        285,
    )
    assert (body["approved_salary_cut_minutes"], body["approved_unpaid_work_minutes"]) == (405, 0)
    audit = await session.scalar(
        select(AuditLog).where(AuditLog.action == "attendance.request_approve")
    )
    assert audit.details["before"] == {"salary_cut_minutes": 120, "unpaid_work_minutes": 285}
    assert audit.details["after"] == {"salary_cut_minutes": 405, "unpaid_work_minutes": 0}


async def test_approve_with_one_value_fills_the_rest(client, clock, staff, gm) -> None:
    clock(at("09:00", "2026-11-03"))
    request = (await _submit(client, staff)).json()
    r = await client.post(
        f"/attendance/requests/{request['id']}/approve",
        json={"unpaid_work_minutes": 5},
        headers=auth(gm),
    )
    assert (r.json()["approved_salary_cut_minutes"], r.json()["approved_unpaid_work_minutes"]) == (
        400,
        5,
    )


async def test_reject_needs_a_reason(client, session, clock, staff, gm) -> None:
    clock(at("09:00", "2026-11-03"))
    request = (await _submit(client, staff)).json()
    url = f"/attendance/requests/{request['id']}/reject"
    for body in ({}, {"reason": ""}, {"reason": "   "}):
        assert_error(await client.post(url, json=body, headers=auth(gm)), 422, "VALIDATION_ERROR")
    r = await client.post(url, json={"reason": "  Not this month  "}, headers=auth(gm))
    assert (r.json()["status"], r.json()["reject_reason"]) == ("rejected", "Not this month")
    audit = await session.scalar(
        select(AuditLog).where(AuditLog.action == "attendance.request_reject")
    )
    assert audit.details["reason"] == "Not this month"


async def test_review_scope_and_permission(
    client, session, clock, workplace, make_user, staff, gm
) -> None:
    clock(at("09:00", "2026-11-03"))
    request = (await _submit(client, staff)).json()
    url = f"/attendance/requests/{request['id']}/approve"
    # Staff and a supervisor without the permission can't review.
    boss = await make_user(Role.SUPERVISOR)
    for user in (staff, boss):
        assert_error(await client.post(url, json={}, headers=auth(user)), 403, "MISSING_PERMISSION")
        assert_error(
            await client.get("/attendance/requests", headers=auth(user)), 403, "MISSING_PERMISSION"
        )
    # A supervisor with the permission reviews staff, not a supervisor.
    lead = await make_user(Role.SUPERVISOR, perms=[REVIEW])
    sup = await make_user(Role.SUPERVISOR)
    await _backdate(session, sup)
    await _october(session, workplace, sup)
    sup_request = (await _submit(client, sup)).json()
    assert_error(
        await client.post(
            f"/attendance/requests/{sup_request['id']}/approve", json={}, headers=auth(lead)
        ),
        403,
        "FORBIDDEN_SCOPE",
    )
    assert_error(
        await client.get(f"/attendance/requests/{sup_request['id']}", headers=auth(lead)),
        403,
        "FORBIDDEN_SCOPE",
    )
    listing = (await client.get("/attendance/requests", headers=auth(lead))).json()
    assert [i["user"]["id"] for i in listing["items"]] == [str(staff.id)]
    # A general manager sees both; the owner reads their own; other staff can't.
    assert (await client.get("/attendance/requests", headers=auth(gm))).json()["total"] == 2
    assert (
        await client.get(f"/attendance/requests/{sup_request['id']}", headers=auth(sup))
    ).status_code == 200
    stranger = await make_user(Role.STAFF)
    assert_error(
        await client.get(f"/attendance/requests/{request['id']}", headers=auth(stranger)),
        403,
        "MISSING_PERMISSION",
    )
    assert_error(
        await client.get(
            "/attendance/requests/00000000-0000-0000-0000-000000000000", headers=auth(gm)
        ),
        404,
        "ATTENDANCE_REQUEST_NOT_FOUND",
    )
    # The supervisor holds the permission and the staff request is in scope.
    r = await client.post(url, json={}, headers=auth(lead))
    assert r.status_code == 200, r.text


async def test_cannot_review_own_request(client, session, clock, workplace, make_user) -> None:
    clock(at("09:00", "2026-11-03"))
    sup = await make_user(Role.SUPERVISOR, perms=[REVIEW])
    await _backdate(session, sup)
    await _october(session, workplace, sup)
    request = (await _submit(client, sup)).json()
    for action, body in (("approve", {}), ("reject", {"reason": "mine"})):
        r = await client.post(
            f"/attendance/requests/{request['id']}/{action}", json=body, headers=auth(sup)
        )
        assert_error(r, 403, "FORBIDDEN_SCOPE")


# --- Listing, no_request, settings ---------------------------------------------------------------


async def test_list_orders_and_filters(
    client, session, clock, workplace, make_user, staff, gm
) -> None:
    clock(at("09:00", "2026-11-03"))
    first = (await _submit(client, staff)).json()
    clock(at("10:00", "2026-11-03"))
    other = await make_user(Role.STAFF)
    await _backdate(session, other)
    await _october(session, workplace, other)
    second = (await _submit(client, other)).json()
    h = auth(gm)
    await client.post(
        f"/attendance/requests/{first['id']}/reject", json={"reason": "no"}, headers=h
    )
    page = (await client.get("/attendance/requests", headers=h)).json()
    # Pending first, then the reviewed ones.
    assert [i["id"] for i in page["items"]] == [second["id"], first["id"]]
    assert (page["total"], page["page_size"], page["pending_count"]) == (2, 20, 1)
    assert page["items"][0]["status"] == "pending" and page["items"][0]["user"]["id"] == str(
        other.id
    )
    by_status = (await client.get("/attendance/requests?status=rejected", headers=h)).json()
    assert [i["id"] for i in by_status["items"]] == [first["id"]]
    for query, expected in (
        ("year=2026&month=10", 2),
        ("month=9", 0),
        (f"user_id={staff.id}", 1),
        ("year=2025", 0),
    ):
        assert (await client.get(f"/attendance/requests?{query}", headers=h)).json()[
            "total"
        ] == expected
    assert_error(
        await client.get("/attendance/requests?status=bogus", headers=h), 422, "VALIDATION_ERROR"
    )


async def test_pending_listed_oldest_first(
    client, session, clock, workplace, make_user, staff, gm
) -> None:
    clock(at("09:00", "2026-11-03"))
    first = (await _submit(client, staff)).json()
    clock(at("10:00", "2026-11-03"))
    other = await make_user(Role.STAFF)
    await _backdate(session, other)
    await _october(session, workplace, other)
    second = (await _submit(client, other)).json()
    page = (await client.get("/attendance/requests?status=pending", headers=auth(gm))).json()
    assert [i["id"] for i in page["items"]] == [first["id"], second["id"]]


async def test_no_request_rows_after_the_deadline(client, clock, staff, gm) -> None:
    h = auth(gm)
    clock(at("09:00", "2026-11-05"))
    assert (await client.get("/attendance/requests?status=no_request", headers=h)).json()[
        "total"
    ] == 0
    clock(at("09:00", "2026-11-08"))
    page = (await client.get("/attendance/requests?status=no_request", headers=h)).json()
    assert page["total"] == 1
    row = page["items"][0]
    assert (row["status"], row["id"], row["missing_minutes"], row["user"]["id"]) == (
        "no_request",
        None,
        405,
        str(staff.id),
    )
    assert (row["year"], row["month"]) == (2026, 10)
    me = (await client.get("/attendance/requests/me?year=2026", headers=auth(staff))).json()
    october = next(m for m in me["months"] if m["month"] == 10)
    assert (october["eligibility"], october["request"]) == ("window_closed", None)
    s = (await client.get("/attendance/me/summary?year=2026&month=10", headers=auth(staff))).json()
    assert (s["request_eligibility"], s["request"], s["month_locked"]) == (
        "window_closed",
        None,
        False,
    )


async def test_settings_superadmin_only(client, session, clock, superadmin, staff, gm) -> None:
    clock(at("09:00", "2026-11-08"))
    url = "/attendance/settings/requests"
    assert (await client.get(url, headers=auth(gm))).json() == {"request_deadline_day": 7}
    assert_error(
        await client.put(url, json={"request_deadline_day": 10}, headers=auth(gm)),
        403,
        "FORBIDDEN_ROLE",
    )
    assert_error(await client.get(url, headers=auth(staff)), 403, "MISSING_PERMISSION")
    for bad in (0, 29, "x"):
        assert_error(
            await client.put(url, json={"request_deadline_day": bad}, headers=auth(superadmin)),
            422,
            "VALIDATION_ERROR",
        )
    assert_error(await _submit(client, staff), 409, "ATTENDANCE_REQUEST_WINDOW_CLOSED")
    r = await client.put(url, json={"request_deadline_day": 10}, headers=auth(superadmin))
    assert (r.status_code, r.json()) == (200, {"request_deadline_day": 10})
    assert (await _submit(client, staff)).status_code == 201
    audit = await session.scalar(
        select(AuditLog).where(AuditLog.action == "attendance.settings_update")
    )
    assert audit.details == {"request_deadline_day": [7, 10]}
    # Same value: no new audit entry.
    await client.put(url, json={"request_deadline_day": 10}, headers=auth(superadmin))
    assert (
        len(
            list(
                await session.scalars(
                    select(AuditLog).where(AuditLog.action == "attendance.settings_update")
                )
            )
        )
        == 1
    )


# --- Notifications -------------------------------------------------------------------------------


async def _alerts(session, type_: str) -> list[Notification]:
    return list(
        await session.scalars(
            select(Notification)
            .where(Notification.type == type_)
            .order_by(Notification.created_at)
            .execution_options(populate_existing=True)
        )
    )


async def test_notifications_for_submit_and_review(
    client, session, clock, make_user, superadmin, staff, gm, telegram_bot
) -> None:
    clock(at("09:00", "2026-11-03"))
    lead = await make_user(Role.SUPERVISOR, perms=[REVIEW], telegram_user_id=7200)
    outsider = await make_user(Role.SUPERVISOR, telegram_user_id=7201)  # no permission
    await _english(session, staff, gm, lead)
    request = (await _submit(client, staff)).json()
    sent = await _alerts(session, "attendance.request_submitted")
    # Reviewers in scope: the supervisor with the permission, the GM and the superadmin.
    assert {n.user_id for n in sent} == {lead.id, gm.id, superadmin.id}
    assert outsider.id not in {n.user_id for n in sent}
    assert sent[0].entity_id.hex == request["id"].replace("-", "")
    assert sent[0].payload["name"] == staff.full_name and sent[0].payload["missing_minutes"] == 405
    texts = {m.chat_id: m for m in telegram_bot.calls("SendMessage")}
    assert set(texts) == {7100, 7200}  # linked reviewers only (the superadmin has no Telegram)
    assert texts[7100].text.startswith(
        f"📝 <b>{staff.full_name}</b> sent a request for October 2026"
    )
    assert "6 h 45" in texts[7100].text and "salary cut 2 h" in texts[7100].text
    assert "unpaid work 4 h 45" in texts[7100].text
    assert (
        texts[7100]
        .reply_markup.inline_keyboard[0][0]
        .web_app.url.endswith(f"/attendance/requests?request={request['id']}")
    )
    # Approved with changes → the employee.
    r = await client.post(
        f"/attendance/requests/{request['id']}/approve",
        json={"salary_cut_minutes": 405, "unpaid_work_minutes": 0, "comment": "Simpler"},
        headers=auth(gm),
    )
    assert r.status_code == 200, r.text
    approved = await _alerts(session, "attendance.request_approved")
    assert [(n.user_id, n.payload["with_changes"], n.payload["comment"]) for n in approved] == [
        (staff.id, True, "Simpler")
    ]
    last = [m for m in telegram_bot.calls("SendMessage") if m.chat_id == 7001][-1]
    assert "was approved" in last.text and "salary cut 6 h 45" in last.text
    assert "with changes" in last.text and "Simpler" in last.text


async def test_rejection_notifies_the_employee(
    client, session, clock, staff, gm, telegram_bot
) -> None:
    await _english(session, staff)
    clock(at("09:00", "2026-11-03"))
    request = (await _submit(client, staff)).json()
    await client.post(
        f"/attendance/requests/{request['id']}/reject",
        json={"reason": "Talk to me"},
        headers=auth(gm),
    )
    (alert,) = await _alerts(session, "attendance.request_rejected")
    assert (alert.user_id, alert.payload["reason"]) == (staff.id, "Talk to me")
    message = [m for m in telegram_bot.calls("SendMessage") if m.chat_id == 7001][-1]
    assert "rejected" in message.text and "“Talk to me”" in message.text
    # The bell shows it with the actor.
    bell = (await client.get("/notifications", headers=auth(staff))).json()
    assert bell["items"][0]["type"] == "attendance.request_rejected"
    assert bell["items"][0]["entity_id"] == request["id"]


async def test_reminder_on_the_first_once(
    client, session, clock, workplace, make_user, staff, telegram_bot
) -> None:
    # A second employee with a small gap and one who already sent a request get nothing.
    small = await make_user(Role.STAFF, telegram_user_id=7002)
    await _backdate(session, small)
    await _october(session, workplace, small, absent=False, late=30)
    await _english(session, staff)
    done = await make_user(Role.STAFF, telegram_user_id=7003)
    await _backdate(session, done)
    await _october(session, workplace, done)
    clock(at("08:00", "2026-11-03"))
    assert (await _submit(client, done)).status_code == 201
    before = len(telegram_bot.calls("SendMessage"))

    # Not the 1st: nothing.
    await scheduler.run_tick(at("08:00", "2026-11-03"), app.state.telegram)
    assert await _alerts(session, "attendance.request_reminder") == []

    await scheduler.run_tick(at("08:00", "2026-11-01"), app.state.telegram)
    (alert,) = await _alerts(session, "attendance.request_reminder")
    assert alert.user_id == staff.id
    assert (alert.payload["year"], alert.payload["month"]) == (2026, 10)
    assert (alert.payload["missing_minutes"], alert.payload["deadline"]) == (405, "2026-11-07")
    message = [m for m in telegram_bot.calls("SendMessage")[before:] if m.chat_id == 7001][-1]
    assert "balance is −6 h 45" in message.text and "7 November" in message.text
    # Once, however many ticks run that day.
    await scheduler.run_tick(at("08:01", "2026-11-01"), app.state.telegram)
    await scheduler.run_tick(at("20:00", "2026-11-01"), app.state.telegram)
    assert len(await _alerts(session, "attendance.request_reminder")) == 1


# --- Permissions and defaults --------------------------------------------------------------------


def test_defaults() -> None:
    assert REVIEW in DEFAULT_PERMISSIONS[Role.GENERAL_MANAGER]
    assert REVIEW not in DEFAULT_PERMISSIONS[Role.SUPERVISOR]
    assert REVIEW not in DEFAULT_PERMISSIONS[Role.STAFF]


async def test_feature_attendance_requests(client, make_user, superadmin, gm) -> None:
    sup = await make_user(Role.SUPERVISOR)
    h = auth(superadmin)
    features = (await client.get(f"/users/{sup.id}/features", headers=h)).json()
    item = {f["code"]: f for m in features["menus"] for f in m["features"]}["attendance_requests"]
    assert (item["menu"], item["current_level"], [lv["level"] for lv in item["levels"]]) == (
        "attendance",
        "off",
        ["off", "full"],
    )
    r = await client.put(
        f"/users/{sup.id}/features/attendance_requests", json={"level": "full"}, headers=h
    )
    assert r.status_code == 200, r.text
    assert (await client.get("/attendance/requests", headers=auth(sup))).status_code == 200
    gm_features = (await client.get(f"/users/{gm.id}/features", headers=h)).json()
    gm_item = {f["code"]: f for m in gm_features["menus"] for f in m["features"]}
    assert gm_item["attendance_requests"]["current_level"] == "full"
