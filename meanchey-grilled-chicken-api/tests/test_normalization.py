import pytest

from app.core.errors import AppError
from app.core.usernames import normalize_telegram_username
from app.models import Role
from tests.conftest import assert_error, auth


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("@Sok_Dara", "sok_dara"),
        ("  @MeanChey99  ", "meanchey99"),
        ("abcde", "abcde"),
        ("a" * 32, "a" * 32),
    ],
)
def test_normalize_valid(raw: str, expected: str) -> None:
    assert normalize_telegram_username(raw) == expected


@pytest.mark.parametrize(
    "raw",
    ["abcd", "a" * 33, "sok-dara", "sok dara", "សុខដារា", "", "@", "superadmin", "@SuperAdmin"],
)
def test_normalize_invalid(raw: str) -> None:
    with pytest.raises(AppError) as exc:
        normalize_telegram_username(raw)
    assert exc.value.code == "INVALID_TELEGRAM_USERNAME"


async def test_create_normalizes_and_login_accepts_any_form(client, superadmin) -> None:
    r = await client.post(
        "/users",
        json={"role": "supervisor", "full_name": "Sok Dara", "telegram_username": "@Sok_Dara"},
        headers=auth(superadmin),
    )
    assert r.status_code == 201, r.text
    assert r.json()["telegram_username"] == "sok_dara"

    # Initial password is the normalized Telegram username; login accepts "@Sok_Dara" too.
    r = await client.post("/auth/login", json={"username": "@SOK_DARA", "password": "sok_dara"})
    assert r.status_code == 200, r.text


async def test_create_rejects_invalid_username(client, superadmin) -> None:
    r = await client.post(
        "/users",
        json={"role": "supervisor", "full_name": "X", "telegram_username": "bad name"},
        headers=auth(superadmin),
    )
    assert_error(r, 422, "INVALID_TELEGRAM_USERNAME")


async def test_duplicate_username_rejected_case_insensitively(
    client, superadmin, make_user
) -> None:
    await make_user(Role.SUPERVISOR, "dara_sup")
    r = await client.post(
        "/users",
        json={"role": "supervisor", "full_name": "X", "telegram_username": "@DARA_SUP"},
        headers=auth(superadmin),
    )
    assert_error(r, 409, "DUPLICATE_TELEGRAM_USERNAME")


async def test_deactivated_username_can_be_reused(client, superadmin, make_user) -> None:
    await make_user(Role.SUPERVISOR, "reused_name", is_active=False)
    r = await client.post(
        "/users",
        json={
            "role": "staff",
            "position": "driver",
            "full_name": "X",
            "telegram_username": "reused_name",
        },
        headers=auth(superadmin),
    )
    assert r.status_code == 201, r.text
