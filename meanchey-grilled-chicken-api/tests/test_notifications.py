"""Production alerts: recipients, rows created with the Finish, Telegram after commit (statuses,
texts, buttons), the bell endpoints, redaction of a superadmin actor, resend of failed ones."""

import pytest
from sqlalchemy import select, update

from app.bot import notify
from app.bot.runtime import TelegramRuntime
from app.bot.setup import create_bot, create_dispatcher
from app.config import get_settings
from app.main import app
from app.models import Language, Notification, Role, User
from tests.conftest import assert_error, auth
from tests.telegram_fakes import RecordingSession
from tests.test_production import PRODUCED, Api, ok, standardize_body

MINI_APP = "https://meanchey.example.com"


@pytest.fixture
async def gm(make_user):
    return await make_user(Role.GENERAL_MANAGER, telegram_user_id=1001)


@pytest.fixture
def api(client, gm) -> Api:
    return Api(client, gm)


@pytest.fixture
async def supplier(client, gm) -> dict:
    return ok(await client.post("/suppliers", json={"name": "Sokha <Farm>"}, headers=auth(gm)), 201)


@pytest.fixture
def tg() -> RecordingSession:
    return RecordingSession()


@pytest.fixture
def webhook_bot(tg, monkeypatch):
    """BOT_MODE=webhook with the API's own (recording) bot on app.state."""
    monkeypatch.setattr(get_settings(), "bot_mode", "webhook")
    monkeypatch.setattr(get_settings(), "mini_app_url", MINI_APP)
    app.state.telegram = TelegramRuntime(
        bot=create_bot(session=tg), dp=create_dispatcher(), secret="s"
    )
    yield tg
    app.state.telegram = None


async def _rows(session, **where) -> list[Notification]:
    stmt = (
        select(Notification)
        .order_by(Notification.created_at, Notification.id)
        .execution_options(populate_existing=True)
    )
    for key, value in where.items():
        stmt = stmt.where(getattr(Notification, key) == value)
    return list(await session.scalars(stmt))


async def _set_plan_level(client, gm, user, level: str) -> None:
    r = await client.put(
        f"/users/{user.id}/features/production_plan", json={"level": level}, headers=auth(gm)
    )
    assert r.status_code == 200, r.text


# --- Recipients and rows -------------------------------------------------------------------------


async def test_recipients_follow_the_plan_permission(
    client, session, gm, superadmin, make_user, api, supplier
) -> None:
    viewer = await make_user(Role.SUPERVISOR)
    await _set_plan_level(client, gm, viewer, "view")
    planner = await make_user(Role.SUPERVISOR)
    await _set_plan_level(client, gm, planner, "full")
    await make_user(Role.SUPERVISOR)  # plan feature off (the default)
    await make_user(Role.STAFF)
    gone = await make_user(Role.SUPERVISOR)
    await _set_plan_level(client, gm, gone, "view")
    await session.execute(update(User).where(User.id == gone.id).values(is_active=False))
    await session.commit()

    batch = await api.step2(supplier, plan=False)
    rows = await _rows(session)
    assert {r.user_id for r in rows} == {gm.id, superadmin.id, viewer.id, planner.id}
    assert {r.type for r in rows} == {"production.processing_finished"}
    row = rows[0]
    assert (row.entity_type, str(row.entity_id)) == ("production_batch", batch["id"])
    assert row.payload == {
        "code": batch["code"],
        "actor_id": str(gm.id),
        "quantity": 10,
        "wings": 20,
        "thighs": 20,
        "repeat": False,
    }
    # BOT_MODE=off in tests: stored, not sent.
    assert {r.telegram_status for r in rows} == {"bot_off"}


async def test_no_alert_for_step_1_or_drafts(session, api, supplier) -> None:
    batch = await api.step1(supplier)
    ok(await api.patch(batch, "produced", **PRODUCED))
    assert await _rows(session) == []


async def test_failed_finish_creates_no_alert(session, api, supplier) -> None:
    batch = await api.step1(supplier)
    assert_error(await api.finish(batch, "produced"), 422, "VALIDATION_ERROR")
    assert await _rows(session) == []


async def test_completed_alert_payload(session, gm, api, supplier) -> None:
    batch = await api.step2(supplier)
    body = standardize_body(big=6, small=7, comment="Two thighs dropped")
    batch = ok(await api.patch(batch, "standardize", **body))
    ok(await api.finish(batch, "standardize"))
    (row,) = await _rows(session, type="production.completed", user_id=gm.id)
    assert row.payload == {
        "code": batch["code"],
        "actor_id": str(gm.id),
        "matches": False,
        "planned_big": 7,
        "planned_small": 5,
        "actual_big": 6,
        "actual_small": 7,
        "comment": "Two thighs dropped",
        "repeat": False,
    }


async def test_repeat_after_reopen(session, gm, api, supplier) -> None:
    batch = await api.step2(supplier)
    batch = ok(await api.reopen(batch, "produced"))
    ok(await api.finish(batch, "produced"))
    rows = await _rows(session, type="production.processing_finished", user_id=gm.id)
    assert [r.payload["repeat"] for r in rows] == [False, True]


# --- Telegram ------------------------------------------------------------------------------------


async def test_telegram_sent_after_commit(
    client, session, gm, superadmin, make_user, api, supplier, webhook_bot
) -> None:
    en = await make_user(Role.SUPERVISOR, telegram_user_id=2002)
    await session.execute(update(User).where(User.id == en.id).values(language=Language.EN))
    await session.commit()
    await _set_plan_level(client, gm, en, "view")

    batch = await api.step2(supplier, plan=False)
    sent = {m.chat_id: m for m in webhook_bot.calls("SendMessage")}
    assert set(sent) == {1001, 2002}  # the superadmin has no Telegram linked
    km, en_msg = sent[1001], sent[2002]
    assert f"<b>{batch['code']}</b>" in km.text and "សូមកំណត់ផែនការវេចខ្ចប់" in km.text
    assert en_msg.text == (
        f"✅ <b>{batch['code']}</b>: processing finished — 10 chickens → 20 wings, 20 thighs. "
        "Set the packaging plan."
    )
    button = en_msg.reply_markup.inline_keyboard[0][0]
    assert button.text == "📋 Open plan"
    assert button.web_app.url == f"{MINI_APP}/workstation/production-plans/{batch['id']}"
    assert km.reply_markup.inline_keyboard[0][0].text == "📋 បើកផែនការ"

    statuses = {r.user_id: r.telegram_status for r in await _rows(session)}
    assert statuses == {gm.id: "sent", en.id: "sent", superadmin.id: "not_linked"}
    assert all(r.sent_at for r in await _rows(session, telegram_status="sent"))


async def test_completed_messages(session, gm, api, supplier, webhook_bot) -> None:
    batch = await api.completed(supplier)
    as_planned = webhook_bot.calls("SendMessage")[-1]
    assert as_planned.text.startswith(f"🎉 <b>{batch['code']}</b>")
    assert "កញ្ចប់ ៤ ដុំ 7" in as_planned.text
    button = as_planned.reply_markup.inline_keyboard[0][0]
    assert button.web_app.url == f"{MINI_APP}/workstation/production/{batch['id']}?step=3"

    await session.execute(update(User).where(User.id == gm.id).values(language=Language.EN))
    await session.commit()
    batch = ok(await api.reopen(batch, "standardize"))
    body = standardize_body(big=6, small=7, comment="<b>3 dropped</b> & 1 torn")
    batch = ok(await api.patch(batch, "standardize", **body))
    ok(await api.finish(batch, "standardize"))
    differs = webhook_bot.calls("SendMessage")[-1]
    assert differs.text == (
        f"⚠️ <b>{batch['code']}</b>: production completed again, different from the plan. "
        "Planned 7 / 5, actual 6 / 7. Comment: “&lt;b&gt;3 dropped&lt;/b&gt; &amp; 1 torn”."
    )
    assert differs.reply_markup.inline_keyboard[0][0].text == "🍗 Open batch"


async def test_no_button_without_an_https_mini_app(api, supplier, webhook_bot, monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "mini_app_url", "http://localhost:5173")
    await api.step2(supplier, plan=False)
    (sent,) = webhook_bot.calls("SendMessage")
    assert sent.reply_markup is None


async def test_telegram_failure_never_fails_the_finish(
    session, gm, api, supplier, webhook_bot, caplog
) -> None:
    webhook_bot.unreachable = True
    batch = await api.step2(supplier, plan=False)
    assert batch["current_step"] == 3
    (row,) = await _rows(session, user_id=gm.id)
    assert row.telegram_status == "failed"
    assert row.telegram_error
    assert "Telegram alert" in caplog.text


async def test_polling_mode_uses_a_short_lived_bot(session, gm, api, supplier, monkeypatch) -> None:
    tg = RecordingSession()
    monkeypatch.setattr(get_settings(), "bot_mode", "polling")
    monkeypatch.setattr(notify, "bot_factory", lambda: create_bot(session=tg))
    await api.step2(supplier, plan=False)
    assert [m.chat_id for m in tg.calls("SendMessage")] == [1001]
    (row,) = await _rows(session, user_id=gm.id)
    assert row.telegram_status == "sent"


async def test_webhook_mode_without_a_runtime_is_bot_off(
    session, gm, api, supplier, monkeypatch
) -> None:
    monkeypatch.setattr(get_settings(), "bot_mode", "webhook")
    await api.step2(supplier, plan=False)
    assert {r.telegram_status for r in await _rows(session)} == {"bot_off"}


async def test_resend_failed(session, gm, api, supplier, monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "bot_mode", "polling")
    monkeypatch.setattr(
        notify, "bot_factory", lambda: create_bot(session=RecordingSession(unreachable=True))
    )
    await api.step2(supplier, plan=False)
    assert (await _rows(session, user_id=gm.id))[0].telegram_status == "failed"

    tg = RecordingSession()
    monkeypatch.setattr(notify, "bot_factory", lambda: create_bot(session=tg))
    assert await notify.resend_failed() == {"sent": 1}
    (row,) = await _rows(session, user_id=gm.id)
    assert (row.telegram_status, row.telegram_error) == ("sent", None)
    assert await notify.resend_failed() == {}


# --- The bell ------------------------------------------------------------------------------------


async def test_list_read_and_read_all_are_own_only(
    client, session, gm, superadmin, api, supplier
) -> None:
    first = await api.step2(supplier, plan=False)
    await api.step2(supplier, plan=False)
    h = auth(gm)
    page = ok(await client.get("/notifications", headers=h))
    assert (page["total"], page["unread_count"]) == (2, 2)
    newest = page["items"][0]
    assert newest["payload"]["code"] != first["code"]  # newest first
    assert "actor_id" not in newest["payload"]
    assert newest["actor"]["id"] == str(gm.id)

    # Someone else's notification is not found.
    theirs = (await _rows(session, user_id=superadmin.id))[0]
    assert_error(
        await client.post(f"/notifications/{theirs.id}/read", headers=h),
        404,
        "NOTIFICATION_NOT_FOUND",
    )
    read = ok(await client.post(f"/notifications/{newest['id']}/read", headers=h))
    assert read["read_at"] is not None
    page = ok(await client.get("/notifications?unread_only=true", headers=h))
    assert (page["total"], page["unread_count"]) == (1, 1)

    assert ok(await client.post("/notifications/read-all", headers=h)) == {
        "updated": 1,
        "unread_count": 0,
    }
    # The superadmin's own are untouched.
    page = ok(await client.get("/notifications", headers=auth(superadmin)))
    assert page["unread_count"] == 2


async def test_staff_have_an_empty_bell(client, make_user, api, supplier) -> None:
    staff = await make_user(Role.STAFF)
    await api.step2(supplier, plan=False)
    page = ok(await client.get("/notifications", headers=auth(staff)))
    assert (page["total"], page["unread_count"], page["items"]) == (0, 0, [])


async def test_superadmin_actor_is_system_for_others(
    client, gm, superadmin, supplier, webhook_bot
) -> None:
    sa_api = Api(client, superadmin)
    await sa_api.step2(supplier, plan=False)
    item = ok(await client.get("/notifications", headers=auth(gm)))["items"][0]
    assert item["actor"] == {
        "id": None,
        "full_name": "System",
        "role": None,
        "telegram_username": None,
        "is_system": True,
    }
    mine = ok(await client.get("/notifications", headers=auth(superadmin)))["items"][0]
    assert mine["actor"]["id"] == str(superadmin.id)
    # The Telegram text never names who finished the step.
    (sent,) = webhook_bot.calls("SendMessage")
    assert "superadmin" not in sent.text.lower() and superadmin.full_name not in sent.text
