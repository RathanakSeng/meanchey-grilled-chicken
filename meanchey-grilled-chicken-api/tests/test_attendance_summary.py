"""The attendance summary (`/attendance/me/summary`, `/attendance/users/{id}/summary`): KPI math
from the records' snapshots and stored minutes, month vs whole year, the day list's bounds,
period validation, and scope."""

from datetime import date

import pytest
from sqlalchemy import update

from app.attendance import summary as summ
from app.models import AttendanceRecord, Role, User
from tests.conftest import assert_error, at, auth


def _record(user, workplace, day: str, shift: str, status: str, **kw) -> AttendanceRecord:
    start, end = kw.pop("times", ("07:00", "12:00") if shift == "morning" else ("13:00", "15:00"))
    check_in = kw.pop("check_in", None)
    check_out = kw.pop("check_out", None)
    return AttendanceRecord(
        user_id=user.id,
        work_date=date.fromisoformat(day),
        shift_code=shift,
        workplace_id=workplace.id,
        scheduled_start=at(start, day),
        scheduled_end=at(end, day),
        status=status,
        check_in_at=at(check_in, day)
        if check_in
        else (None if status == "absent" else at(start, day)),
        check_out_at=at(check_out, day) if check_out else None,
        checkout_status=kw.pop("checkout", "checked_out" if check_out else None),
        source=kw.pop("source", "mini_app"),
        **kw,
    )


@pytest.fixture
async def month(session, workplace, make_user):
    """A staff member (since 2026-09-20) with a mixed October and one September shift. The
    clock is 2026-10-13."""
    staff = await make_user(Role.STAFF)
    await session.execute(
        update(User).where(User.id == staff.id).values(created_at=at("10:00", "2026-09-20"))
    )
    r = _record
    session.add_all(
        [
            # Early 20 + overtime 25 → 300 + 45.
            r(staff, workplace, "2026-10-01", "morning", "present", check_in="06:40",
              check_out="12:25", early_minutes=20, overtime_minutes=25),
            # Late 10, forgot check-out → 110.
            r(staff, workplace, "2026-10-01", "afternoon", "late", check_in="13:10",
              late_minutes=10, checkout="forgot_checkout"),
            r(staff, workplace, "2026-10-02", "morning", "absent"),
            # After a schedule change (13:30–16:00 = 150), overtime 5 → 155.
            r(staff, workplace, "2026-10-02", "afternoon", "present", times=("13:30", "16:00"),
              check_out="16:05", overtime_minutes=5),
            # Corrected: late 15, overtime 10 → 295.
            r(staff, workplace, "2026-10-05", "morning", "late", check_in="07:15",
              check_out="12:10", late_minutes=15, overtime_minutes=10, corrected=True,
              correction_reason="Phone had no GPS", source="correction"),
            r(staff, workplace, "2026-10-05", "afternoon", "absent"),
            # September (whole year only).
            r(staff, workplace, "2026-09-30", "morning", "present", check_out="12:00"),
        ]
    )  # fmt: skip
    await session.commit()
    return staff


async def _get(client, user, url: str):
    r = await client.get(url, headers=auth(user))
    assert r.status_code == 200, r.text
    return r.json()


async def test_month_kpis(client, clock, month) -> None:
    clock("16:00")
    body = await _get(client, month, "/attendance/me/summary?year=2026&month=10")
    k = body["kpis"]
    assert k["present"] == {
        "total_shifts": 4,
        "by_shift": {"morning": 2, "afternoon": 2},
        "minutes": 345 + 110 + 155 + 295,
    }
    assert k["absent"] == {
        "total_shifts": 2,
        "by_shift": {"morning": 1, "afternoon": 1},
        "minutes": 300 + 120,
    }
    assert k["late"] == {"count": 2, "minutes": 25}
    assert k["early"] == {"count": 1, "minutes": 20}
    assert k["overtime"] == {"count": 3, "minutes": 40}
    assert (k["missing_minutes"], k["extra_minutes"], k["balance_minutes"]) == (445, 60, -385)
    assert k["forgot_checkout"] == 1
    assert body["period"] == {
        "year": 2026,
        "month": 10,
        "start": "2026-10-01",
        "end": "2026-10-13",
    }
    assert [s["code"] for s in body["shifts"]] == ["morning", "afternoon"]
    assert body["shifts"][0]["name_en"] == "Morning shift"
    assert body["employee"]["user"]["id"] == str(month.id)
    assert body["employee"]["workplace"]["name"] == "Mean Chey"
    assert body["employee"]["since"] == "2026-09-20"


async def test_month_days(client, clock, month) -> None:
    clock("16:00")
    days = (await _get(client, month, "/attendance/me/summary"))["days"]  # default: this month
    # 1 → 13 October (today), newest first; no future dates.
    assert [d["date"] for d in days] == [f"2026-10-{n:02d}" for n in range(13, 0, -1)]
    by_date = {d["date"]: {s["code"]: s for s in d["shifts"]} for d in days}
    assert {c: s["status"] for c, s in by_date["2026-10-03"].items()} == {
        "morning": "none",
        "afternoon": "none",
    }
    assert by_date["2026-10-03"]["morning"]["record"] is None
    fixed = by_date["2026-10-05"]["morning"]
    assert fixed["status"] == "late"
    rec = fixed["record"]
    assert (rec["late_minutes"], rec["overtime_minutes"], rec["corrected"]) == (15, 10, True)
    assert rec["correction_reason"] == "Phone had no GPS"
    assert rec["check_out_at"].startswith("2026-10-05T12:10:00+07:00")
    first = by_date["2026-10-01"]
    assert (first["morning"]["record"]["early_minutes"], first["afternoon"]["status"]) == (
        20,
        "late",
    )
    assert first["afternoon"]["record"]["checkout_status"] == "forgot_checkout"


async def test_whole_year_and_creation_date(client, clock, month) -> None:
    clock("16:00")
    body = await _get(client, month, "/attendance/me/summary?year=2026")
    assert body["period"] == {
        "year": 2026,
        "month": None,
        "start": "2026-01-01",
        "end": "2026-10-13",
    }
    assert body["kpis"]["present"]["total_shifts"] == 5
    assert body["kpis"]["present"]["by_shift"] == {"morning": 3, "afternoon": 2}
    # Listed from the account's creation (20 September), not 1 January.
    dates = [d["date"] for d in body["days"]]
    assert (dates[0], dates[-1], len(dates)) == ("2026-10-13", "2026-09-20", 24)

    # A past month: the whole month, from the creation date.
    body = await _get(client, month, "/attendance/me/summary?year=2026&month=9")
    assert body["period"]["end"] == "2026-09-30"
    assert [d["date"] for d in body["days"]][::10] == ["2026-09-30", "2026-09-20"]
    assert body["kpis"]["present"]["minutes"] == 300
    assert body["kpis"]["balance_minutes"] == 0

    # Before the account existed: nothing.
    body = await _get(client, month, "/attendance/me/summary?year=2026&month=8")
    assert body["days"] == [] and body["kpis"]["present"]["total_shifts"] == 0


@pytest.mark.parametrize(
    "query", ["year=2026&month=11", "year=2027", "month=13", "month=0", "year=1999"]
)
async def test_invalid_periods(client, clock, month, query) -> None:
    clock("16:00")
    r = await client.get(f"/attendance/me/summary?{query}", headers=auth(month))
    assert_error(r, 422, "VALIDATION_ERROR")


async def test_today_counts_once_recorded(client, session, clock, workplace, make_user) -> None:
    staff = await make_user(Role.STAFF)
    clock("06:50")
    r = await client.post(
        "/attendance/check-in",
        json={"latitude": 11.562108, "longitude": 104.888535, "accuracy_m": 15},
        headers=auth(staff),
    )
    assert r.status_code == 200, r.text
    body = await _get(client, staff, "/attendance/me/summary")
    assert body["kpis"]["present"]["total_shifts"] == 1
    assert body["kpis"]["early"] == {"count": 1, "minutes": 10}
    # Today is listed (its afternoon has no record yet).
    today = {s["code"]: s["status"] for s in body["days"][0]["shifts"]}
    assert today == {"morning": "present", "afternoon": "none"}


def test_kpis_balance_sign() -> None:
    assert summ.kpis([], ["morning"]).balance_minutes == 0


async def test_self_endpoint_only_for_tracked_employees(client, make_user) -> None:
    gm = await make_user(Role.GENERAL_MANAGER)
    assert_error(
        await client.get("/attendance/me/summary", headers=auth(gm)),
        403,
        "ATTENDANCE_NOT_REQUIRED",
    )


async def test_manager_scope(client, clock, superadmin, month, make_user) -> None:
    clock("16:00")
    url = f"/attendance/users/{month.id}/summary?year=2026&month=10"
    gm = await make_user(Role.GENERAL_MANAGER)
    body = await _get(client, gm, url)
    assert body["kpis"]["balance_minutes"] == -385
    assert body["employee"]["role"] == "staff"

    sup = await make_user(Role.SUPERVISOR, perms=["attendance.view"])
    assert (await _get(client, sup, url))["employee"]["user"]["id"] == str(month.id)
    # A supervisor sees staff, not other supervisors.
    other = await make_user(Role.SUPERVISOR)
    assert_error(
        await client.get(f"/attendance/users/{other.id}/summary", headers=auth(sup)),
        403,
        "FORBIDDEN_SCOPE",
    )
    body = await _get(client, gm, f"/attendance/users/{other.id}/summary")
    assert body["employee"]["role"] == "supervisor"
    # Without attendance.view; staff can't see others.
    plain = await make_user(Role.SUPERVISOR, perms=[])
    assert_error(await client.get(url, headers=auth(plain)), 403, "MISSING_PERMISSION")
    assert_error(await client.get(url, headers=auth(month)), 403, "MISSING_PERMISSION")
    # Hidden accounts are "not found"; untracked roles aren't recorded.
    assert_error(
        await client.get(f"/attendance/users/{superadmin.id}/summary", headers=auth(gm)),
        404,
        "USER_NOT_FOUND",
    )
    other_gm = await make_user(Role.GENERAL_MANAGER)
    r = await client.get(f"/attendance/users/{other_gm.id}/summary", headers=auth(superadmin))
    assert_error(r, 422, "ATTENDANCE_NOT_REQUIRED")


async def test_deactivated_employee_history(client, session, clock, month, make_user) -> None:
    clock("16:00")
    await session.execute(update(User).where(User.id == month.id).values(is_active=False))
    await session.commit()
    gm = await make_user(Role.GENERAL_MANAGER)
    body = await _get(client, gm, f"/attendance/users/{month.id}/summary")
    assert body["employee"]["is_active"] is False
    assert body["kpis"]["present"]["total_shifts"] == 4
