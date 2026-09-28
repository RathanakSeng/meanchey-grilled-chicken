import json
import time
from urllib.parse import urlencode

import pytest

from app.core.errors import AppError
from app.core.telegram_auth import compute_init_data_hash, validate_init_data
from app.models import Role
from tests.conftest import TEST_BOT_TOKEN, assert_error


def make_init_data(
    tg_id: int,
    username: str | None,
    *,
    auth_date: int | None = None,
    bot_token: str = TEST_BOT_TOKEN,
) -> str:
    user = {"id": tg_id, "first_name": "Dara", "language_code": "km"}
    if username is not None:
        user["username"] = username
    fields = {
        "query_id": "AAHdF6IQAAAAAN0XohDhrOrc",
        "user": json.dumps(user, separators=(",", ":")),
        "auth_date": str(auth_date if auth_date is not None else int(time.time())),
    }
    fields["hash"] = compute_init_data_hash(fields, bot_token)
    return urlencode(fields)


def test_validate_valid() -> None:
    tg = validate_init_data(make_init_data(42, "Sok_Dara"), TEST_BOT_TOKEN, 86400)
    assert tg.id == 42
    assert tg.username == "Sok_Dara"


def test_validate_tampered() -> None:
    data = make_init_data(42, "sok_dara").replace("sok_dara", "someone_else")
    with pytest.raises(AppError) as exc:
        validate_init_data(data, TEST_BOT_TOKEN, 86400)
    assert exc.value.code == "INVALID_TELEGRAM_DATA"


def test_validate_wrong_bot_token() -> None:
    data = make_init_data(42, "sok_dara", bot_token="999:other-bot")
    with pytest.raises(AppError) as exc:
        validate_init_data(data, TEST_BOT_TOKEN, 86400)
    assert exc.value.code == "INVALID_TELEGRAM_DATA"


def test_validate_expired() -> None:
    data = make_init_data(42, "sok_dara", auth_date=int(time.time()) - 86400 - 60)
    with pytest.raises(AppError) as exc:
        validate_init_data(data, TEST_BOT_TOKEN, 86400)
    assert exc.value.code == "TELEGRAM_DATA_EXPIRED"


def test_validate_missing_hash() -> None:
    with pytest.raises(AppError) as exc:
        validate_init_data("auth_date=1&user=%7B%7D", TEST_BOT_TOKEN, 86400)
    assert exc.value.code == "INVALID_TELEGRAM_DATA"


async def _tg_login(client, init_data: str):
    return await client.post("/auth/telegram", json={"init_data": init_data})


async def test_login_binds_by_username_then_matches_by_id(client, session, make_user) -> None:
    user = await make_user(Role.STAFF, "sok_dara")
    r = await _tg_login(client, make_init_data(1001, "@Sok_Dara"))
    assert r.status_code == 200, r.text

    await session.refresh(user)
    assert user.telegram_user_id == 1001

    # After binding, match by ID even if the Telegram username changed.
    r = await _tg_login(client, make_init_data(1001, "renamed_account"))
    assert r.status_code == 200, r.text

    # Another Telegram account with the bound username no longer matches.
    r = await _tg_login(client, make_init_data(2002, "sok_dara"))
    assert_error(r, 403, "USER_NOT_REGISTERED")


async def test_unregistered_telegram_user(client) -> None:
    assert_error(
        await _tg_login(client, make_init_data(3003, "stranger_x")), 403, "USER_NOT_REGISTERED"
    )
    assert_error(await _tg_login(client, make_init_data(3003, None)), 403, "USER_NOT_REGISTERED")


async def test_tampered_and_expired_rejected_by_api(client, make_user) -> None:
    await make_user(Role.STAFF, "sok_dara")
    tampered = make_init_data(1001, "sok_dara").replace("Dara", "Hack")
    assert_error(await _tg_login(client, tampered), 401, "INVALID_TELEGRAM_DATA")
    expired = make_init_data(1001, "sok_dara", auth_date=int(time.time()) - 2 * 86400)
    assert_error(await _tg_login(client, expired), 401, "TELEGRAM_DATA_EXPIRED")


async def test_telegram_login_still_enforces_password_change(client, make_user) -> None:
    await make_user(Role.STAFF, "new_staff", must_change_password=True)
    r = await _tg_login(client, make_init_data(4004, "new_staff"))
    assert r.status_code == 200
    assert r.json()["must_change_password"] is True
    headers = {"Authorization": f"Bearer {r.json()['access_token']}"}
    assert_error(
        await client.patch("/me", json={"language": "en"}, headers=headers),
        403,
        "PASSWORD_CHANGE_REQUIRED",
    )


async def test_deactivated_user_cannot_login_via_telegram(client, make_user) -> None:
    await make_user(Role.STAFF, "gone_staff", telegram_user_id=5005, is_active=False)
    assert_error(
        await _tg_login(client, make_init_data(5005, "gone_staff")), 403, "ACCOUNT_DISABLED"
    )
