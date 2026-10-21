"""Pressing Start in the bot binds a Telegram account by its username (the Mini App sign-in
rule), so alerts reach users who never opened the app; managers see who isn't linked yet."""

import pytest
from sqlalchemy import select, update

from app.bot import notify
from app.bot.runtime import TelegramRuntime
from app.bot.setup import create_bot, create_dispatcher
from app.config import get_settings
from app.main import app
from app.models import AuditLog, Language, Notification, Role, User
from tests.conftest import assert_error, auth
from tests.telegram_fakes import RecordingSession, command_update
from tests.test_production import Api, ok

WEBHOOK = "http://test/api/telegram/webhook"
SECRET = "start_bind_secret"
HEADERS = {"X-Telegram-Bot-Api-Secret-Token": SECRET}
LINKED_KM = "✅ គណនី Telegram របស់អ្នកត្រូវបានភ្ជាប់។ ការជូនដំណឹងនឹងផ្ញើមកទីនេះ។"
LINKED_EN = "✅ Your Telegram account is now linked. Alerts will be sent here."


@pytest.fixture
def tg(monkeypatch) -> RecordingSession:
    """BOT_MODE=webhook with a recording bot: /start updates and alerts both go through it."""
    tg = RecordingSession()
    monkeypatch.setattr(get_settings(), "bot_mode", "webhook")
    app.state.telegram = TelegramRuntime(
        bot=create_bot(session=tg), dp=create_dispatcher(), secret=SECRET
    )
    yield tg
    app.state.telegram = None


async def _start(client, tg_id: int, username: str | None) -> None:
    body = command_update("/start", tg_id=tg_id, username=username)
    r = await client.post(WEBHOOK, json=body, headers=HEADERS)
    assert r.status_code == 200


async def _bound_id(session, user: User) -> int | None:
    return await session.scalar(
        select(User.telegram_user_id)
        .where(User.id == user.id)
        .execution_options(populate_existing=True)
    )


async def _bound_audits(session) -> list[AuditLog]:
    rows = await session.scalars(select(AuditLog).where(AuditLog.action == "auth.telegram_bound"))
    return list(rows)


async def test_start_binds_by_username(client, session, make_user, tg) -> None:
    sup = await make_user(Role.SUPERVISOR, "dara_supervisor")
    # Telegram usernames are case-insensitive: the stored one is normalized.
    await _start(client, 7001, "Dara_Supervisor")
    assert await _bound_id(session, sup) == 7001
    (reply,) = tg.calls("SendMessage")
    assert reply.chat_id == 7001
    assert LINKED_KM in reply.text
    (row,) = await _bound_audits(session)
    assert (row.actor_id, row.target_user_id) == (sup.id, sup.id)
    assert row.details == {"telegram_user_id": 7001, "via": "bot_start"}

    # Pressing Start again changes nothing (and says nothing about linking).
    await _start(client, 7001, "dara_supervisor")
    assert LINKED_KM not in tg.calls("SendMessage")[-1].text
    assert len(await _bound_audits(session)) == 1


async def test_start_reply_in_the_bound_users_language(client, session, make_user, tg) -> None:
    staff = await make_user(Role.STAFF, "dara_staff_en")
    await session.execute(update(User).where(User.id == staff.id).values(language=Language.EN))
    await session.commit()
    await _start(client, 7002, "dara_staff_en")
    (reply,) = tg.calls("SendMessage")
    assert reply.text.startswith("Hello Dara!")
    assert LINKED_EN in reply.text


async def test_start_never_rebinds(client, session, make_user, superadmin, tg) -> None:
    # This Telegram id already belongs to an active user: nothing else is bound to it.
    await make_user(Role.GENERAL_MANAGER, "first_owner", telegram_user_id=7003)
    unbound = await make_user(Role.SUPERVISOR, "second_user")
    await _start(client, 7003, "second_user")
    assert await _bound_id(session, unbound) is None

    # The username belongs to an account bound to another Telegram id: it stays as it is.
    taken = await make_user(Role.SUPERVISOR, "taken_user", telegram_user_id=7004)
    await _start(client, 7005, "taken_user")
    assert await _bound_id(session, taken) == 7004

    # The superadmin links with its one-time link, never by username.
    await session.execute(
        update(User).where(User.id == superadmin.id).values(telegram_username="the_owner")
    )
    await session.commit()
    await _start(client, 7006, "the_owner")
    assert await _bound_id(session, superadmin) is None

    # Deactivated accounts, unknown usernames and chats without a username.
    gone = await make_user(Role.STAFF, "gone_staff", is_active=False)
    await _start(client, 7007, "gone_staff")
    assert await _bound_id(session, gone) is None
    await _start(client, 7008, "nobody_here")
    await _start(client, 7009, None)

    assert await _bound_audits(session) == []
    replies = tg.calls("SendMessage")
    assert len(replies) == 6 and not any(LINKED_KM in m.text for m in replies)


async def test_next_alert_is_sent_after_start(client, session, make_user, tg) -> None:
    gm = await make_user(Role.GENERAL_MANAGER)
    sup = await make_user(Role.SUPERVISOR, "plan_supervisor")
    r = await client.put(
        f"/users/{sup.id}/features/production_plan", json={"level": "view"}, headers=auth(gm)
    )
    assert r.status_code == 200, r.text
    api = Api(client, gm)
    supplier = ok(await client.post("/suppliers", json={"name": "Farm"}, headers=auth(gm)), 201)

    await api.step2(supplier, plan=False)
    await _start(client, 7010, "plan_supervisor")
    batch = await api.step2(supplier, plan=False)

    (alert,) = [m for m in tg.calls("SendMessage") if batch["code"] in m.text]
    assert alert.chat_id == 7010
    rows = await session.scalars(
        select(Notification.telegram_status)
        .where(Notification.user_id == sup.id)
        .order_by(Notification.created_at)
    )
    assert list(rows) == ["not_linked", "sent"]


async def test_managers_see_who_is_linked(client, superadmin, make_user, tg) -> None:
    gm = await make_user(Role.GENERAL_MANAGER)
    sup = await make_user(Role.SUPERVISOR, "list_supervisor")

    async def linked() -> dict[str, bool]:
        page = ok(await client.get("/users", headers=auth(gm)))
        return {u["id"]: u["telegram_linked"] for u in page["items"]}

    before = await linked()
    assert before[str(sup.id)] is False
    assert str(superadmin.id) not in before  # hidden as usual
    assert ok(await client.get(f"/users/{sup.id}", headers=auth(gm)))["telegram_linked"] is False

    await _start(client, 7011, "list_supervisor")
    assert (await linked())[str(sup.id)] is True
    detail = ok(await client.get(f"/users/{sup.id}", headers=auth(gm)))
    assert detail["telegram_linked"] is True
    assert "7011" not in str(detail)  # the Telegram id itself is never shown


# --- The app's "connect Telegram" hint -----------------------------------------------------------


async def _me(client, user) -> dict:
    return ok(await client.get("/auth/me", headers=auth(user)))


async def test_telegram_alerts_flag(client, make_user) -> None:
    gm = await make_user(Role.GENERAL_MANAGER)
    plain = await make_user(Role.SUPERVISOR, perms=[])
    staff = await make_user(Role.STAFF, perms=[])

    # Tracked employees get attendance reminders; GMs hold the alert permissions by default.
    assert (await _me(client, staff))["telegram_alerts"] is True
    assert (await _me(client, plain))["telegram_alerts"] is True
    assert (await _me(client, gm))["telegram_alerts"] is True

    # A supervisor with attendance switched off and no alert permission gets nothing.
    r = await client.patch(
        f"/users/{plain.id}", json={"attendance_tracked": False}, headers=auth(gm)
    )
    assert r.status_code == 200, r.text
    assert (await _me(client, plain))["telegram_alerts"] is False
    r = await client.put(
        f"/users/{plain.id}/features/production_plan", json={"level": "view"}, headers=auth(gm)
    )
    assert r.status_code == 200, r.text
    me = await _me(client, plain)
    assert me["telegram_alerts"] is True and me["user"]["telegram_linked"] is False


@pytest.mark.parametrize("role", [Role.GENERAL_MANAGER, Role.SUPERVISOR, Role.STAFF])
async def test_bot_link_for_everyone(client, make_user, role) -> None:
    user = await make_user(role)
    r = await client.get("/me/telegram-bot", headers=auth(user))
    assert ok(r) == {"url": "https://t.me/meanchey_test_bot"}


async def test_bot_link_without_a_bot_token(client, make_user, monkeypatch) -> None:
    monkeypatch.setattr(notify, "_bot_username", None)
    monkeypatch.setattr(get_settings(), "telegram_bot_token", "")
    staff = await make_user(Role.STAFF)
    assert_error(
        await client.get("/me/telegram-bot", headers=auth(staff)), 503, "TELEGRAM_NOT_CONFIGURED"
    )
