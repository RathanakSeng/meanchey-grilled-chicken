"""Migration 0031: the four attendance alert notification types; downgrade deletes those
notifications and restores the old check."""

import asyncio

import pytest
from alembic import command
from sqlalchemy.exc import IntegrityError

from app.models import Role
from tests.test_migration_step_dates import _alembic, _run

TYPES = (
    "attendance.checked_in",
    "attendance.checked_out",
    "attendance.shift_absent",
    "attendance.shift_forgot_checkout",
)


def _insert(user_id, type_: str) -> str:
    return (
        "INSERT INTO notifications (id, user_id, type, entity_type, entity_id) VALUES "
        f"(gen_random_uuid(), '{user_id}', '{type_}', 'attendance_shift', gen_random_uuid())"
    )


async def test_types_round_trip(make_user) -> None:
    gm = await make_user(Role.GENERAL_MANAGER)
    await asyncio.to_thread(_round_trip, gm.id)


def _round_trip(user_id) -> None:
    for type_ in TYPES:
        asyncio.run(_run(_insert(user_id, type_)))
    _alembic(command.downgrade, "0030")
    try:
        rows = asyncio.run(
            _run(
                "SELECT count(*) FROM notifications WHERE type IN "
                f"({', '.join(repr(t) for t in TYPES)})"
            )
        )
        assert rows == [(0,)]
        with pytest.raises(IntegrityError):
            asyncio.run(_run(_insert(user_id, "attendance.checked_in")))
    finally:
        _alembic(command.upgrade, "head")
    asyncio.run(_run(_insert(user_id, "attendance.shift_absent")))
