"""Migration 0026: order boxes can be plastic bags and delivery bags; downgrade and back."""

import asyncio

from alembic import command

from tests.test_migration_step_dates import _alembic, _run


def _color_check() -> str:
    ((definition,),) = asyncio.run(
        _run(
            # The naming convention doubles the prefix: ck_order_boxes_ck_order_boxes_color.
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conrelid = 'order_boxes'::regclass AND conname LIKE '%\\_color'"
        )
    )
    return definition


def test_order_bags_migration_round_trip() -> None:
    assert "plastic_bag" in _color_check() and "delivery_bag" in _color_check()
    _alembic(command.downgrade, "0025")
    try:
        old = _color_check()
        assert "white" in old and "black" in old
        assert "plastic_bag" not in old and "delivery_bag" not in old
    finally:
        _alembic(command.upgrade, "head")
    assert "plastic_bag" in _color_check() and "delivery_bag" in _color_check()
