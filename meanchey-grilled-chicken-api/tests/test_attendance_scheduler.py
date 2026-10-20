"""The attendance scheduler (app/attendance/scheduler.py): absent records, forgot check-out,
reminders (right people, once, skipped when disabled / not linked / window closed), idempotent
ticks, catch-up after a restart, the advisory lock, and each workplace's own schedule."""

from datetime import timedelta

from sqlalchemy import select, text, update

from app.attendance import scheduler
from app.db import SessionLocal
from app.main import app
from app.models import AttendanceRecord, AttendanceReminder, Role, User
from tests.conftest import at, auth, branch_position, make_workplace, position, set_schedule


async def _records(session, shift="morning") -> dict:
    rows = await session.scalars(
        select(AttendanceRecord)
        .where(AttendanceRecord.shift_code == shift)
        .execution_options(populate_existing=True)
    )
    return {r.user_id: r for r in rows}


async def _reminders(session) -> list[AttendanceReminder]:
    return list(
        await session.scalars(
            select(AttendanceReminder)
            .order_by(AttendanceReminder.created_at)
            .execution_options(populate_existing=True)
        )
    )


async def _tick(now):
    """A tick with the app's bot (the recording one in tests using `telegram_bot`)."""
    return await scheduler.run_tick(now, app.state.telegram)


async def _backdate(session, *users, hm="05:00") -> None:
    """Make the users exist since `hm` on the test day (the scheduler only counts employees
    who existed at the cutoff)."""
    await session.execute(
        update(User).where(User.id.in_([u.id for u in users])).values(created_at=at(hm))
    )
    await session.commit()


async def test_absent_after_the_cutoff(client, session, clock, workplace, make_user) -> None:
    present = await make_user(Role.STAFF)
    missing = await make_user(Role.STAFF)
    sup = await make_user(Role.SUPERVISOR)
    gm = await make_user(Role.GENERAL_MANAGER)
    inactive = await make_user(Role.STAFF, is_active=False)
    await _backdate(session, present, missing, sup, gm, inactive)
    clock("07:00")
    r = await client.post("/attendance/check-in", json=position(), headers=auth(present))
    assert r.status_code == 200

    result = await _tick(at("07:44:59"))
    assert result is not None and result.absent == 0
    result = await _tick(at("07:45"))
    assert result.absent == 2
    records = await _records(session)
    assert set(records) == {present.id, missing.id, sup.id}
    absent = records[missing.id]
    assert (absent.status, absent.source, absent.check_in_at) == ("absent", "auto", None)
    assert absent.scheduled_start == at("07:00")
    assert absent.workplace_id == workplace.id
    # Idempotent.
    assert (await _tick(at("07:46"))).absent == 0
    # Someone created after the cutoff isn't absent for that shift.
    late_hire = await make_user(Role.STAFF)
    await _backdate(session, late_hire, hm="09:00")
    await _tick(at("09:05"))
    assert late_hire.id not in await _records(session)


async def test_forgot_check_out(client, session, clock, workplace, make_user) -> None:
    out, forgot = await make_user(Role.STAFF), await make_user(Role.STAFF)
    await _backdate(session, out, forgot)
    clock("07:00")
    for u in (out, forgot):
        await client.post("/attendance/check-in", json=position(), headers=auth(u))
    clock("12:10")
    await client.post("/attendance/check-out", json=position(), headers=auth(out))
    assert (await _tick(at("12:59:59"))).forgot_checkout == 0
    assert (await _tick(at("13:00"))).forgot_checkout == 1
    records = await _records(session)
    assert records[out.id].checkout_status == "checked_out"
    assert records[forgot.id].checkout_status == "forgot_checkout"
    assert records[forgot.id].check_out_at is None
    assert (await _tick(at("13:01"))).forgot_checkout == 0
    # The afternoon at 16:00 the same way.
    clock("13:00")
    await client.post("/attendance/check-in", json=position(), headers=auth(out))
    assert (await _tick(at("16:00"))).forgot_checkout == 1
    assert (await _records(session, "afternoon"))[out.id].checkout_status == "forgot_checkout"


async def test_catch_up_after_a_restart(session, workplace, make_user) -> None:
    """The first tick after downtime marks every passed cutoff of today, but sends no reminder
    whose window has closed."""
    staff = await make_user(Role.STAFF, telegram_user_id=7001)
    await _backdate(session, staff)
    result = await _tick(at("14:00"))
    assert result.absent == 2  # morning and afternoon
    assert result.reminders == []
    assert await _reminders(session) == []


async def test_check_in_reminders(session, workplace, make_user, telegram_bot) -> None:
    linked = await make_user(Role.STAFF, telegram_user_id=7001)
    sup = await make_user(Role.SUPERVISOR, telegram_user_id=7002)
    unlinked = await make_user(Role.STAFF)
    await make_user(Role.GENERAL_MANAGER, telegram_user_id=7003)
    await make_user(Role.STAFF, telegram_user_id=7004, is_active=False)
    await _backdate(session, linked, sup, unlinked)

    assert (await _tick(at("06:29"))).reminders == []
    result = await _tick(at("06:30"))
    assert len(result.reminders) == 2
    assert result.sent == {"sent": 2}
    sent = telegram_bot.calls("SendMessage")
    assert {m.chat_id for m in sent} == {7001, 7002}
    assert sent[0].text == "🕡 ម៉ោងចុះវត្តមានវេនព្រឹកបានបើកហើយ រហូតដល់ 07:44។"
    button = sent[0].reply_markup.inline_keyboard[0][0]
    assert button.text == "📍 ចុះវត្តមាន"
    assert button.web_app.url == "https://app.example.com/attendance/check"
    # Once only.
    assert (await _tick(at("06:31"))).reminders == []
    assert len(telegram_bot.calls("SendMessage")) == 2
    rows = await _reminders(session)
    assert {(r.kind, r.telegram_status) for r in rows} == {("check_in", "sent")}


async def test_check_in_reminder_skips_who_already_checked_in(
    client, session, clock, workplace, make_user, telegram_bot
) -> None:
    early = await make_user(Role.STAFF, telegram_user_id=7001)
    await _backdate(session, early, hm="05:00")
    clock("06:30")
    # Checked in during the same minute, before the tick.
    await client.post("/attendance/check-in", json=position(), headers=auth(early))
    assert (await _tick(at("06:30"))).reminders == []
    # Only the check-in confirmation, no reminder.
    assert [m.text[0] for m in telegram_bot.calls("SendMessage")] == ["✅"]


async def test_check_out_reminders_in_english(
    client, session, clock, workplace, make_user, telegram_bot
) -> None:
    checked_in = await make_user(Role.STAFF, telegram_user_id=7001)
    absent = await make_user(Role.STAFF, telegram_user_id=7002)
    await _backdate(session, checked_in, absent)
    await session.execute(update(User).where(User.id == checked_in.id).values(language="en"))
    await session.commit()
    clock("07:05")
    await client.post("/attendance/check-in", json=position(), headers=auth(checked_in))
    await _tick(at("07:45"))  # absent
    telegram_bot.requests.clear()
    result = await _tick(at("12:00"))
    assert len(result.reminders) == 1
    (sent,) = telegram_bot.calls("SendMessage")
    assert sent.chat_id == 7001
    assert sent.text == "🕛 You can check out of the morning shift until 12:59."
    assert sent.reply_markup.inline_keyboard[0][0].text == "📍 Check out"
    # The afternoon check-in reminder at 12:30 goes to both (English text for the first).
    telegram_bot.requests.clear()
    await _tick(at("12:30"))
    texts = {m.chat_id: m.text for m in telegram_bot.calls("SendMessage")}
    assert texts[7001] == "🕡 Afternoon check-in is open until 13:44."
    assert texts[7002] == "🕡 ម៉ោងចុះវត្តមានវេនរសៀលបានបើកហើយ រហូតដល់ 13:44។"


async def test_reminders_disabled(session, workplace, make_user, telegram_bot) -> None:
    staff = await make_user(Role.STAFF, telegram_user_id=7001)
    await _backdate(session, staff)
    await set_schedule(session, workplace, reminders_enabled=False)
    result = await _tick(at("06:30"))
    assert result.reminders == []
    assert telegram_bot.calls("SendMessage") == []
    # Absent records still come.
    assert (await _tick(at("07:45"))).absent == 1


async def test_turning_reminders_off_skips_waiting_ones(session, workplace, make_user) -> None:
    staff = await make_user(Role.STAFF, telegram_user_id=7002)
    await _backdate(session, staff)
    async with SessionLocal() as s:
        await scheduler.tick(s, at("06:30"))  # queued and claimed, but never sent
        await s.execute(
            update(AttendanceReminder).values(telegram_status="pending")
        )  # as if the send never happened
        await s.commit()
    await set_schedule(session, workplace, reminders_enabled=False)
    result = await _tick(at("06:31"))
    assert result.skipped == 1 and result.reminders == []


async def test_each_workplace_has_its_own_schedule(
    client, session, clock, workplace, make_user, telegram_bot
) -> None:
    """Default 07:00 (open 06:30, absent 07:45); Branch 2 08:00 (open 07:45, absent 08:20,
    check-out until 12:30), reminders off at a third workplace."""
    branch = await make_workplace(session)
    quiet = await make_workplace(session, "Quiet", metres_north=9000, reminders_enabled=False)
    here = await make_user(Role.STAFF, telegram_user_id=8001, workplace_id=workplace.id)
    there = await make_user(Role.STAFF, telegram_user_id=8002, workplace_id=branch.id)
    muted = await make_user(Role.STAFF, telegram_user_id=8003, workplace_id=quiet.id)
    await _backdate(session, here, there, muted)

    result = await _tick(at("06:30"))
    assert {r.user_id for r in await _reminders(session)} == {here.id}
    result = await _tick(at("07:45"))
    assert result.absent == 1  # only the default workplace's employee
    assert set(await _records(session)) == {here.id}
    reminded = {r.user_id for r in await _reminders(session)}
    assert reminded == {here.id, there.id}  # the branch's window opened; Quiet stays silent
    branch_reminder = next(r for r in await _reminders(session) if r.user_id == there.id)
    assert branch_reminder.window_closes_at == at("08:20")

    clock(at("08:00"))
    r = await client.post("/attendance/check-in", json=branch_position(), headers=auth(there))
    assert r.status_code == 200, r.text
    result = await _tick(at("08:20"))
    # Quiet (morning 08:00, absent after 20 min) is marked absent too; the branch's employee
    # checked in.
    records = await _records(session)
    assert records[muted.id].status == "absent"
    assert records[muted.id].workplace_id == quiet.id
    assert records[there.id].status == "present"
    # The branch's check-out window closes at 12:31 (12:00 + 30 + 1 min): forgot from then.
    assert (await _tick(at("12:30"))).forgot_checkout == 0
    assert (await _tick(at("12:31"))).forgot_checkout == 1
    assert (await _records(session))[there.id].checkout_status == "forgot_checkout"


async def test_employee_of_an_archived_workplace_counts_at_the_default(
    session, workplace, make_user
) -> None:
    old = await make_workplace(session, "Old")
    staff = await make_user(Role.STAFF, workplace_id=old.id)
    await _backdate(session, staff)
    old.is_active = False
    await session.commit()
    assert (await _tick(at("07:45"))).absent == 1
    record = (await _records(session))[staff.id]
    assert record.workplace_id == workplace.id


async def test_pending_reminders_never_sent_late(session, workplace, make_user) -> None:
    """A reminder left pending (e.g. a crash between commit and send) is skipped once its
    window has closed."""
    staff = await make_user(Role.STAFF, telegram_user_id=7001)
    await _backdate(session, staff)
    session.add(
        AttendanceReminder(
            user_id=staff.id,
            work_date=at("06:30").date(),
            shift_code="morning",
            kind="check_in",
            window_closes_at=at("07:45"),
        )
    )
    await session.commit()
    result = await _tick(at("08:00"))
    assert result.skipped == 1 and result.reminders == []
    (row,) = await _reminders(session)
    assert row.telegram_status == "skipped"


async def test_reminder_outcomes_without_bot(session, workplace, make_user) -> None:
    staff = await make_user(Role.STAFF, telegram_user_id=7001)
    await _backdate(session, staff)
    result = await _tick(at("06:30"))
    assert result.sent == {"bot_off": 1}


async def test_reminder_send_failure_is_recorded(session, workplace, make_user, telegram_bot):
    staff = await make_user(Role.STAFF, telegram_user_id=7001)
    await _backdate(session, staff)
    telegram_bot.unreachable = True
    result = await _tick(at("06:30"))
    assert result.sent == {"failed": 1}
    (row,) = await _reminders(session)
    assert row.telegram_status == "failed" and row.telegram_error


async def test_advisory_lock_one_worker(session, workplace, make_user) -> None:
    staff = await make_user(Role.STAFF)
    await _backdate(session, staff)
    async with SessionLocal() as holder:
        await holder.execute(
            text("SELECT pg_advisory_xact_lock(:k)"), {"k": scheduler.SCHEDULER_LOCK_KEY}
        )
        # Another worker's tick skips while the lock is held.
        assert await _tick(at("08:00")) is None
        await holder.rollback()
    assert (await _tick(at("08:00"))).absent == 1


async def test_only_today(session, workplace, make_user) -> None:
    staff = await make_user(Role.STAFF)
    await _backdate(session, staff)
    await _tick(at("08:00") + timedelta(days=1))
    rows = list(await session.scalars(select(AttendanceRecord)))
    assert [r.work_date.isoformat() for r in rows] == ["2026-10-14"]
