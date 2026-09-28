from datetime import timedelta

from sqlalchemy import func, select

from app.models import AuditLog, Role, utcnow
from tests.conftest import DEFAULT_PASSWORD, assert_error


async def _login(client, username: str, password: str):
    return await client.post("/auth/login", json={"username": username, "password": password})


async def test_five_failures_lock_the_account(client, session, make_user) -> None:
    user = await make_user(Role.SUPERVISOR, "lock_me")
    for _ in range(4):
        assert_error(await _login(client, "lock_me", "wrong"), 401, "INVALID_CREDENTIALS")
    r = await _login(client, "lock_me", "wrong")
    assert_error(r, 423, "ACCOUNT_LOCKED")
    assert "locked_until" in r.json()["error"]["details"]

    # Even the correct password is rejected while locked.
    assert_error(await _login(client, "lock_me", DEFAULT_PASSWORD), 423, "ACCOUNT_LOCKED")

    locked = await session.scalar(
        select(func.count(AuditLog.id)).where(
            AuditLog.action == "auth.locked", AuditLog.target_user_id == user.id
        )
    )
    assert locked == 1


async def test_login_works_after_lock_expires(client, session, make_user) -> None:
    user = await make_user(Role.SUPERVISOR, "lock_me")
    for _ in range(5):
        await _login(client, "lock_me", "wrong")

    await session.refresh(user)
    assert user.locked_until is not None
    user.locked_until = utcnow() - timedelta(seconds=1)
    await session.commit()

    r = await _login(client, "lock_me", DEFAULT_PASSWORD)
    assert r.status_code == 200, r.text


async def test_successful_login_resets_counter(client, session, make_user) -> None:
    user = await make_user(Role.SUPERVISOR, "reset_me")
    for _ in range(4):
        await _login(client, "reset_me", "wrong")
    assert (await _login(client, "reset_me", DEFAULT_PASSWORD)).status_code == 200
    for _ in range(4):
        assert_error(await _login(client, "reset_me", "wrong"), 401, "INVALID_CREDENTIALS")
    await session.refresh(user)
    assert user.failed_login_count == 4


async def test_failed_logins_are_audited(client, session) -> None:
    await _login(client, "superadmin", "wrong")
    count = await session.scalar(
        select(func.count(AuditLog.id)).where(AuditLog.action == "auth.login_failed")
    )
    assert count == 1
