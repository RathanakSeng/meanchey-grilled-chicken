import pytest
from sqlalchemy.exc import IntegrityError

from app.core.security import hash_password
from app.models import Role, User
from tests.conftest import assert_error, auth


async def test_db_allows_only_one_superadmin(session) -> None:
    session.add(User(role=Role.SUPERADMIN, full_name="Second", password_hash=hash_password("x")))
    with pytest.raises(IntegrityError, match="uq_users_single_superadmin"):
        await session.flush()


async def test_db_allows_only_one_active_gm(session, make_user) -> None:
    await make_user(Role.GENERAL_MANAGER, "gm_one")
    session.add(
        User(
            role=Role.GENERAL_MANAGER,
            full_name="Second GM",
            telegram_username="gm_two",
            password_hash=hash_password("x"),
        )
    )
    with pytest.raises(IntegrityError, match="uq_users_single_active_gm"):
        await session.flush()


async def test_db_allows_second_gm_when_first_is_inactive(session, make_user) -> None:
    await make_user(Role.GENERAL_MANAGER, "gm_old", is_active=False)
    await make_user(Role.GENERAL_MANAGER, "gm_new")


async def test_db_requires_position_only_for_staff(session) -> None:
    session.add(
        User(
            role=Role.STAFF,
            full_name="No position",
            telegram_username="no_position",
            password_hash=hash_password("x"),
        )
    )
    with pytest.raises(IntegrityError, match="ck_users_position_staff_only"):
        await session.flush()


async def test_db_requires_telegram_username_for_non_superadmin(session) -> None:
    session.add(User(role=Role.SUPERVISOR, full_name="No tg", password_hash=hash_password("x")))
    with pytest.raises(IntegrityError, match="ck_users_telegram_username_required"):
        await session.flush()


async def test_api_rejects_second_gm(client, superadmin, make_user) -> None:
    await make_user(Role.GENERAL_MANAGER, "gm_one")
    r = await client.post(
        "/users",
        json={"role": "general_manager", "full_name": "GM 2", "telegram_username": "gm_two"},
        headers=auth(superadmin),
    )
    assert_error(r, 409, "GM_ALREADY_EXISTS")


async def test_api_cannot_reactivate_gm_while_another_is_active(
    client, superadmin, make_user
) -> None:
    old = await make_user(Role.GENERAL_MANAGER, "gm_old", is_active=False)
    await make_user(Role.GENERAL_MANAGER, "gm_new")
    r = await client.post(f"/users/{old.id}/reactivate", headers=auth(superadmin))
    assert_error(r, 409, "GM_ALREADY_EXISTS")


async def test_nobody_can_create_a_superadmin(client, superadmin, make_user) -> None:
    gm = await make_user(Role.GENERAL_MANAGER)
    for actor in (superadmin, gm):
        r = await client.post(
            "/users",
            json={"role": "superadmin", "full_name": "SA2", "telegram_username": "another_sa"},
            headers=auth(actor),
        )
        assert_error(r, 403, "FORBIDDEN_SCOPE")


async def test_position_rules(client, superadmin) -> None:
    r = await client.post(
        "/users",
        json={"role": "staff", "full_name": "S", "telegram_username": "staff_nopos"},
        headers=auth(superadmin),
    )
    assert_error(r, 422, "POSITION_REQUIRED")
    r = await client.post(
        "/users",
        json={
            "role": "supervisor",
            "position": "worker",
            "full_name": "S",
            "telegram_username": "sup_withpos",
        },
        headers=auth(superadmin),
    )
    assert_error(r, 422, "POSITION_NOT_ALLOWED")
