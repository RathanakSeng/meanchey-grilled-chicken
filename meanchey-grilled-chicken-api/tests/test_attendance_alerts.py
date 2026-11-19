"""Attendance alerts to general managers (app/attendance/alerts.py): recipients (GMs holding
`attendance.checkin_alerts` only), check-in / check-out messages with late / early / overtime,
none for corrections, the scheduler's grouped absent / forgot check-out messages (non-empty, once
per group, catch-up, personal cutoffs, several workplaces, days off / untracked left out), texts
in both languages, the feature (default, backfill)."""

import uuid
from datetime import date, timedelta

from sqlalchemy import delete, select, update

from app.attendance import alerts, scheduler
from app.main import app
from app.models import Language, Notification, Role, User, UserPermission
from app.permissions.registry import DEFAULT_PERMISSIONS
from app.permissions.sync import backfill_defaults
from tests.conftest import at, auth, branch_position, make_workplace, position, set_schedule
from tests.test_attendance_employee_schedules import morning_only, put, scheduler_gm

PERMISSION = "attendance.checkin_alerts"
GM_DEFAULTS = sorted(DEFAULT_PERMISSIONS[Role.GENERAL_MANAGER])
WITHOUT_ALERTS = [c for c in GM_DEFAULTS if c != PERMISSION]


async def _notifications(session, type_: str | None = None) -> list[Notification]:
    stmt = select(Notification).order_by(Notification.created_at, Notification.id)
    if type_:
        stmt = stmt.where(Notification.type == type_)
    return list(await session.scalars(stmt.execution_options(populate_existing=True)))


async def _named(session, make_user, name: str, role: Role, **kw) -> User:
    user = await make_user(role, **kw)
    user.full_name = name
    await session.commit()
    return user


async def _backdate(session, *users) -> None:
    await session.execute(
        update(User).where(User.id.in_([u.id for u in users])).values(created_at=at("05:00"))
    )
    await session.commit()


async def _check(client, clock, user, action: str, hm: str, body=None) -> dict:
    clock(hm)
    r = await client.post(f"/attendance/{action}", json=body or position(), headers=auth(user))
    assert r.status_code == 200, r.text
    return r.json()["record"]


async def _tick(now):
    return await scheduler.run_tick(now, app.state.telegram)


def _texts(tg) -> dict[int, list[str]]:
    """The alerts sent per chat (the employees' own confirmations left out)."""
    out: dict[int, list[str]] = {}
    for m in tg.calls("SendMessage"):
        if m.text[:1] in "🟢🔵🔴🟠":
            out.setdefault(m.chat_id, []).append(m.text)
    return out


# --- Access --------------------------------------------------------------------------------------


async def test_recipients_are_gms_with_the_permission(
    client, session, clock, workplace, make_user, superadmin, telegram_bot
) -> None:
    gm = await make_user(Role.GENERAL_MANAGER, telegram_user_id=9101)
    off = await make_user(Role.GENERAL_MANAGER, telegram_user_id=9102, perms=WITHOUT_ALERTS)
    await make_user(Role.SUPERVISOR, telegram_user_id=9103)
    await make_user(Role.STAFF, telegram_user_id=9104)
    await make_user(Role.GENERAL_MANAGER, telegram_user_id=9105, is_active=False)
    superadmin.telegram_user_id = 9106
    await session.commit()
    staff = await _named(session, make_user, "Dara", Role.STAFF)
    await _check(client, clock, staff, "check-in", "07:00")

    (row,) = await _notifications(session)
    assert (row.user_id, row.type, row.entity_type) == (
        gm.id,
        "attendance.checked_in",
        "attendance_record",
    )
    assert row.telegram_status == "sent"
    assert list(_texts(telegram_bot)) == [9101]
    # The superadmin switches it off per GM: nothing more for them.
    r = await client.put(
        f"/users/{gm.id}/features/attendance_checkin_alerts",
        json={"level": "off"},
        headers=auth(superadmin),
    )
    assert r.status_code == 200, r.text
    await _check(client, clock, staff, "check-out", "12:05")
    assert len(await _notifications(session)) == 1
    # And back on.
    r = await client.put(
        f"/users/{off.id}/features/attendance_checkin_alerts",
        json={"level": "full"},
        headers=auth(superadmin),
    )
    assert r.status_code == 200, r.text


async def test_feature_is_the_superadmins_and_on_by_default(
    client, session, make_user, superadmin
) -> None:
    gm = await make_user(Role.GENERAL_MANAGER)
    sup = await make_user(Role.SUPERVISOR)
    assert PERMISSION in DEFAULT_PERMISSIONS[Role.GENERAL_MANAGER]
    r = await client.get(f"/users/{gm.id}/features", headers=auth(superadmin))
    features = {f["code"]: f for m in r.json()["menus"] for f in m["features"]}
    alerts_feature = features["attendance_checkin_alerts"]
    assert alerts_feature["current_level"] == "full"
    assert [lv["level"] for lv in alerts_feature["levels"]] == ["off", "full"]
    r = await client.get(f"/users/{sup.id}/features", headers=auth(superadmin))
    codes = {f["code"] for m in r.json()["menus"] for f in m["features"]}
    assert "attendance_checkin_alerts" not in codes
    # A GM can't set it for another GM (only the superadmin manages GMs).
    other = await make_user(Role.GENERAL_MANAGER)
    r = await client.put(
        f"/users/{other.id}/features/attendance_checkin_alerts",
        json={"level": "off"},
        headers=auth(gm),
    )
    assert r.status_code == 403


async def test_backfill_to_existing_active_gms(session, make_user) -> None:
    gm = await make_user(Role.GENERAL_MANAGER, perms=WITHOUT_ALERTS)
    gone = await make_user(Role.GENERAL_MANAGER, perms=WITHOUT_ALERTS, is_active=False)
    sup = await make_user(Role.SUPERVISOR)
    await session.execute(
        delete(UserPermission).where(UserPermission.permission_code == PERMISSION)
    )
    await backfill_defaults(session, [PERMISSION])
    await session.commit()
    holders = set(
        await session.scalars(
            select(UserPermission.user_id).where(UserPermission.permission_code == PERMISSION)
        )
    )
    assert gm.id in holders
    assert not holders & {gone.id, sup.id}


# --- Per event -----------------------------------------------------------------------------------


async def test_check_in_and_out_texts(
    client, session, clock, workplace, make_user, telegram_bot
) -> None:
    await set_schedule(session, workplace, count_early_checkin=True, count_overtime=True)
    en = await make_user(Role.GENERAL_MANAGER, telegram_user_id=9201)
    en.language = Language.EN
    await make_user(Role.GENERAL_MANAGER, telegram_user_id=9202)
    await session.commit()
    dara = await _named(session, make_user, "Dara <b>", Role.STAFF)
    sok = await _named(session, make_user, "Sok", Role.SUPERVISOR)
    vy = await _named(session, make_user, "Vy", Role.STAFF)

    rec = await _check(client, clock, dara, "check-in", "07:12")
    await _check(client, clock, sok, "check-in", "06:40")
    await _check(client, clock, vy, "check-in", "07:00")
    await _check(client, clock, dara, "check-out", "12:05")
    await _check(client, clock, vy, "check-out", "12:00")

    texts = _texts(telegram_bot)
    assert texts[9201] == [
        "🟢 <b>Dara &lt;b&gt;</b> checked in — Morning shift, 07:12 · late 12 min",
        "🟢 <b>Sok</b> checked in — Morning shift, 06:40 · 20 min early",
        "🟢 <b>Vy</b> checked in — Morning shift, 07:00",
        "🔵 <b>Dara &lt;b&gt;</b> checked out — Morning shift, 12:05 · +5 min overtime",
        "🔵 <b>Vy</b> checked out — Morning shift, 12:00",
    ]
    assert texts[9202][0] == (
        "🟢 <b>Dara &lt;b&gt;</b> បានចុះវត្តមាន — វេនព្រឹក ម៉ោង 07:12 · មកយឺត 12 នាទី"
    )
    assert texts[9202][3] == (
        "🔵 <b>Dara &lt;b&gt;</b> បានចុះចេញ — វេនព្រឹក ម៉ោង 12:05 · ថែមម៉ោង +5 នាទី"
    )
    # No button: the chat stays light.
    alerts_sent = [m for m in telegram_bot.calls("SendMessage") if m.chat_id in (9201, 9202)]
    assert all(m.reply_markup is None for m in alerts_sent)
    # The bell: the record, the employee and the figures.
    row = (await _notifications(session, "attendance.checked_in"))[0]
    assert row.entity_id == uuid.UUID(rec["id"])
    assert row.payload | {"repeat": False} == {
        "user_id": str(dara.id),
        "name": "Dara <b>",
        "date": "2026-10-13",
        "shift_code": "morning",
        "time": "07:12",
        "workplace": None,
        "late_minutes": 12,
        "early_minutes": 0,
        "repeat": False,
    }
    r = await client.get("/notifications", headers=auth(en))
    item = r.json()["items"][0]
    assert item["type"] == "attendance.checked_out" and item["payload"]["overtime_minutes"] == 0


async def test_none_for_corrections_or_refusals(
    client, session, clock, workplace, make_user
) -> None:
    gm = await make_user(Role.GENERAL_MANAGER)
    staff = await make_user(Role.STAFF)
    rec = await _check(client, clock, staff, "check-in", "07:20")
    assert len(await _notifications(session)) == 1
    clock("09:00")
    body = {"status": "present", "check_in_time": "06:58", "reason": "Phone had no GPS"}
    r = await client.patch(f"/attendance/records/{rec['id']}", json=body, headers=auth(gm))
    assert r.status_code == 200, r.text
    # A refused check-in (too far) records nothing.
    other = await make_user(Role.STAFF)
    clock("07:10")
    r = await client.post("/attendance/check-in", json=position(5000), headers=auth(other))
    assert r.status_code == 422
    assert len(await _notifications(session)) == 1


async def test_the_workplace_is_named_with_several(
    client, session, clock, workplace, make_user, telegram_bot
) -> None:
    gm = await make_user(Role.GENERAL_MANAGER, telegram_user_id=9301)
    gm.language = Language.EN
    await session.commit()
    branch = await make_workplace(session, "Branch <2>")
    staff = await _named(session, make_user, "Dara", Role.STAFF, workplace_id=branch.id)
    await _check(client, clock, staff, "check-in", "08:00", branch_position())
    assert _texts(telegram_bot)[9301] == [
        "🟢 <b>Dara</b> checked in — Morning shift, 08:00 · Branch &lt;2&gt;"
    ]


# --- Per shift (scheduler) -----------------------------------------------------------------------


async def test_absent_and_forgot_check_out_lists(
    client, session, clock, workplace, make_user, telegram_bot
) -> None:
    en = await make_user(Role.GENERAL_MANAGER, telegram_user_id=9401)
    en.language = Language.EN
    km = await make_user(Role.GENERAL_MANAGER, telegram_user_id=9402)
    await session.commit()
    present = await _named(session, make_user, "Vy", Role.STAFF)
    forgot = await _named(session, make_user, "Sok", Role.STAFF)
    a = await _named(session, make_user, "Dara", Role.STAFF)
    b = await _named(session, make_user, "Bopha & co", Role.SUPERVISOR)
    await _backdate(session, present, forgot, a, b)
    for u in (present, forgot):
        await _check(client, clock, u, "check-in", "07:00")
    await _check(client, clock, present, "check-out", "12:10")
    telegram_bot.requests.clear()

    await _tick(at("07:44"))
    assert await _notifications(session, "attendance.shift_absent") == []
    result = await _tick(at("07:45"))
    assert result.absent == 2
    rows = await _notifications(session, "attendance.shift_absent")
    assert {r.user_id for r in rows} == {en.id, km.id}
    assert rows[0].entity_type == "attendance_shift"
    key = alerts.ShiftKey(workplace.id, date(2026, 10, 13), "morning", at("07:45"))
    assert {r.entity_id for r in rows} == {key.entity_id()}
    assert rows[0].payload["names"] == ["Bopha & co", "Dara"]
    assert rows[0].payload["cutoff"] == "07:45"
    texts = _texts(telegram_bot)
    assert texts[9401] == [
        "🔴 Morning shift Tue 13 Oct 2026 — didn't check in (absent): Bopha &amp; co, Dara"
    ]
    assert texts[9402] == ["🔴 វេនព្រឹក 13 តុលា 2026 — មិនបានចុះវត្តមាន (អវត្តមាន)៖ Bopha &amp; co, Dara"]

    # Forgot check-out when the window closes (13:00): only Sok.
    telegram_bot.requests.clear()
    await _tick(at("12:59"))
    assert await _notifications(session, "attendance.shift_forgot_checkout") == []
    await _tick(at("13:00"))
    assert _texts(telegram_bot)[9401] == [
        "🟠 Morning shift Tue 13 Oct 2026 — forgot to check out: Sok"
    ]
    assert _texts(telegram_bot)[9402] == ["🟠 វេនព្រឹក 13 តុលា 2026 — ភ្លេចចុះចេញ៖ Sok"]
    # Afternoon: everyone absent (one message); nobody checked in, so no forgot check-out.
    await _tick(at("16:30"))
    absent = await _notifications(session, "attendance.shift_absent")
    assert len(absent) == 4
    assert absent[-1].payload["names"] == ["Bopha & co", "Dara", "Sok", "Vy"]
    assert len(await _notifications(session, "attendance.shift_forgot_checkout")) == 2


async def test_once_per_group_and_catch_up(session, workplace, make_user, telegram_bot) -> None:
    gm = await make_user(Role.GENERAL_MANAGER, telegram_user_id=9501)
    staff = await make_user(Role.STAFF)
    await _backdate(session, staff)
    # Downtime until 14:00: the catch-up records both shifts and alerts each once.
    await _tick(at("14:00"))
    rows = await _notifications(session, "attendance.shift_absent")
    assert sorted(r.payload["shift_code"] for r in rows) == ["afternoon", "morning"]
    assert all(r.user_id == gm.id for r in rows)
    for hm in ("14:01", "16:00", "23:00"):
        await _tick(at(hm))
    assert len(await _notifications(session, "attendance.shift_absent")) == 2
    # Even if the same group records someone again (switched back on), the group isn't resent.
    key = alerts.ShiftKey(workplace.id, date(2026, 10, 13), "morning", at("07:45"))
    assert await alerts.shift_alerts(session, "attendance.shift_absent", {key: {staff.id}}) == []
    # A tick with nothing recorded sends nothing.
    assert (await _tick(at("23:30"))).alerts == []


async def test_nothing_on_days_off_or_for_untracked(
    session, workplace, make_user, telegram_bot
) -> None:
    await make_user(Role.GENERAL_MANAGER, telegram_user_id=9601)
    later = await make_user(Role.STAFF)
    later.attendance_start_date = date(2026, 10, 20)
    await make_user(Role.STAFF, is_active=False)
    await make_user(Role.GENERAL_MANAGER)
    await session.commit()
    await _backdate(session, later)
    # Untracked / not started / inactive / managers: nobody to list, no message.
    result = await _tick(at("14:00"))
    assert result.absent == 0
    assert await _notifications(session) == []
    # A day off (Tuesday not tracked): nothing even for tracked staff.
    staff = await make_user(Role.STAFF)
    await _backdate(session, staff)
    await set_schedule(session, workplace, weekdays=[1, 3, 4, 5, 6, 7])
    tomorrow_off = at("14:00") + timedelta(days=7)
    await _tick(tomorrow_off)
    assert await _notifications(session) == []


async def test_personal_schedules_grouped_by_cutoff(
    client, session, clock, workplace, make_user, telegram_bot
) -> None:
    gm = await scheduler_gm(make_user)
    gm.telegram_user_id = 9701
    gm.language = Language.EN
    await session.commit()
    own = await _named(session, make_user, "Own", Role.STAFF)
    own2 = await _named(session, make_user, "Own two", Role.STAFF)
    other = await _named(session, make_user, "Other", Role.STAFF)
    await _backdate(session, own, own2, other)
    clock("05:00")
    assert (await put(client, gm, [own], **morning_only())).status_code == 200
    assert (await put(client, gm, [own2], **morning_only())).status_code == 200

    await _tick(at("07:45"))
    (row,) = await _notifications(session, "attendance.shift_absent")
    assert row.payload["names"] == ["Other"]
    # Their own cutoff (07:30 + 45 min): one message for both of them.
    await _tick(at("08:15"))
    rows = await _notifications(session, "attendance.shift_absent")
    assert len(rows) == 2
    assert rows[1].payload["names"] == ["Own", "Own two"]
    assert rows[1].payload["cutoff"] == "08:15"
    assert rows[0].entity_id != rows[1].entity_id
    assert _texts(telegram_bot)[9701] == [
        "🔴 Morning shift Tue 13 Oct 2026 — didn't check in (absent): Other",
        "🔴 Morning shift Tue 13 Oct 2026 — didn't check in (absent): Own, Own two",
    ]


async def test_several_workplaces_one_message_each(
    session, workplace, make_user, telegram_bot
) -> None:
    gm = await make_user(Role.GENERAL_MANAGER, telegram_user_id=9801)
    gm.language = Language.EN
    await session.commit()
    branch = await make_workplace(session, "Branch 2")
    here = await _named(session, make_user, "Here", Role.STAFF)
    there = await _named(session, make_user, "There", Role.STAFF, workplace_id=branch.id)
    await _backdate(session, here, there)
    await _tick(at("08:20"))  # the default's cutoff 07:45, the branch's 08:20
    rows = await _notifications(session, "attendance.shift_absent")
    rows.sort(key=lambda r: r.payload["cutoff"])
    assert [(r.payload["workplace"], r.payload["names"]) for r in rows] == [
        (workplace.name, ["Here"]),
        ("Branch 2", ["There"]),
    ]
    branch_line = "🔴 Morning shift Tue 13 Oct 2026 · Branch 2 — didn't check in (absent): There"
    # One message per workplace (sent in no particular order).
    assert set(_texts(telegram_bot)[9801]) == {
        f"🔴 Morning shift Tue 13 Oct 2026 · {workplace.name} — didn't check in (absent): Here",
        branch_line,
    }


async def test_rerun_sends_nothing(session, workplace, make_user) -> None:
    """Replaying past cutoffs (a holiday removed) is a manager's change, not an event."""
    await make_user(Role.GENERAL_MANAGER)
    staff = await make_user(Role.STAFF)
    await _backdate(session, staff)
    result = await scheduler.rerun(session, [(workplace.id, date(2026, 10, 13))], at("14:00"))
    await session.commit()
    assert result.absent == 2
    assert await _notifications(session) == []
