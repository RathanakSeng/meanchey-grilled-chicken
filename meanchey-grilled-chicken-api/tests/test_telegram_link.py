"""The superadmin links its Telegram account with a one-time deep link (/start link_<token>)."""

from datetime import timedelta
from urllib.parse import parse_qs, urlsplit

import pytest
from sqlalchemy import select, update

from app.bot import notify
from app.bot.runtime import TelegramRuntime
from app.bot.setup import create_bot, create_dispatcher
from app.config import get_settings
from app.core.security import hash_token
from app.main import app
from app.models import AuditLog, Role, TelegramLinkToken, User, utcnow
from tests.conftest import assert_error, auth
from tests.telegram_fakes import RecordingSession, command_update

WEBHOOK = "http://test/api/telegram/webhook"
SECRET = "test_webhook-secret_123"
HEADERS = {"X-Telegram-Bot-Api-Secret-Token": SECRET}


@pytest.fixture
def tg(monkeypatch) -> RecordingSession:
    session = RecordingSession()
    monkeypatch.setattr(notify, "_bot_username", None)  # getMe is cached per process
    app.state.telegram = TelegramRuntime(
        bot=create_bot(session=session), dp=create_dispatcher(), secret=SECRET
    )
    yield session
    app.state.telegram = None


async def _link(client, superadmin) -> str:
    r = await client.post("/me/telegram-link", headers=auth(superadmin))
    assert r.status_code == 200, r.text
    url = r.json()["url"]
    parts = urlsplit(url)
    assert (parts.scheme, parts.netloc, parts.path) == ("https", "t.me", "/meanchey_test_bot")
    start = parse_qs(parts.query)["start"][0]
    assert start.startswith("link_")
    return start


async def _start(client, start: str, tg_id: int = 5555):
    r = await client.post(
        WEBHOOK, json=command_update(f"/start {start}", tg_id=tg_id), headers=HEADERS
    )
    assert r.status_code == 200


async def _linked_id(session, user) -> int | None:
    return await session.scalar(
        select(User.telegram_user_id)
        .where(User.id == user.id)
        .execution_options(populate_existing=True)
    )


async def test_link_flow(client, session, superadmin, tg) -> None:
    me = (await client.get("/auth/me", headers=auth(superadmin))).json()
    assert me["user"]["telegram_linked"] is False

    start = await _link(client, superadmin)
    raw = start.removeprefix("link_")
    token = await session.scalar(select(TelegramLinkToken))
    # Stored hashed, never raw; valid for 10 minutes.
    assert token.token_hash == hash_token(raw) and raw not in token.token_hash
    assert timedelta(minutes=9) < token.expires_at - token.created_at <= timedelta(minutes=10)

    await _start(client, start)
    (reply,) = tg.calls("SendMessage")
    assert reply.chat_id == 5555
    assert reply.text == "✅ បានភ្ជាប់ Telegram រួចរាល់។"
    assert "superadmin" not in reply.text.lower()
    assert await _linked_id(session, superadmin) == 5555
    me = (await client.get("/auth/me", headers=auth(superadmin))).json()
    assert me["user"]["telegram_linked"] is True
    assert "5555" not in str(me)
    action = await session.scalar(
        select(AuditLog.action).where(AuditLog.action == "profile.telegram_link")
    )
    assert action == "profile.telegram_link"

    # Single use.
    await _start(client, start, tg_id=6666)
    assert tg.calls("SendMessage")[-1].text.startswith("⚠️")
    assert await _linked_id(session, superadmin) == 5555


async def test_expired_or_unknown_token(client, session, superadmin, tg) -> None:
    start = await _link(client, superadmin)
    await session.execute(
        update(TelegramLinkToken).values(expires_at=utcnow() - timedelta(seconds=1))
    )
    await session.commit()
    await _start(client, start)
    await _start(client, "link_not-a-real-token")
    texts = [m.text for m in tg.calls("SendMessage")]
    assert len(texts) == 2 and all(t.startswith("⚠️") for t in texts)
    assert texts[0] == texts[1]  # the same neutral reply
    assert await _linked_id(session, superadmin) is None


async def test_id_bound_to_another_user_is_rejected(
    client, session, superadmin, make_user, tg
) -> None:
    await make_user(Role.GENERAL_MANAGER, telegram_user_id=5555)
    start = await _link(client, superadmin)
    await _start(client, start)
    assert tg.calls("SendMessage")[-1].text.startswith("⚠️")
    assert await _linked_id(session, superadmin) is None


async def test_unlink(client, session, superadmin, tg) -> None:
    await _start(client, await _link(client, superadmin))
    r = await client.delete("/me/telegram-link", headers=auth(superadmin))
    assert r.status_code == 204
    assert await _linked_id(session, superadmin) is None
    assert (await client.delete("/me/telegram-link", headers=auth(superadmin))).status_code == 204


@pytest.mark.parametrize("role", [Role.GENERAL_MANAGER, Role.SUPERVISOR, Role.STAFF])
async def test_only_the_superadmin(client, make_user, tg, role) -> None:
    user = await make_user(role)
    assert_error(await client.post("/me/telegram-link", headers=auth(user)), 403, "FORBIDDEN_ROLE")
    assert_error(
        await client.delete("/me/telegram-link", headers=auth(user)), 403, "FORBIDDEN_ROLE"
    )


async def test_without_a_bot_token(client, superadmin, monkeypatch) -> None:
    monkeypatch.setattr(notify, "_bot_username", None)
    monkeypatch.setattr(get_settings(), "telegram_bot_token", "")
    assert_error(
        await client.post("/me/telegram-link", headers=auth(superadmin)),
        503,
        "TELEGRAM_NOT_CONFIGURED",
    )


async def test_plain_start_still_greets(client, tg) -> None:
    await _start(client, "")
    assert "មាន់អាំងមានជ័យ" in tg.calls("SendMessage")[0].text
