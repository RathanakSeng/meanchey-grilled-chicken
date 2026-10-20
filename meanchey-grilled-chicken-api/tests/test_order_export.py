"""Delivery note Excel export (the Excel is built in the browser): the order_export feature
(orders.export_delivery_note) and the supplier block endpoint behind it."""

import pytest

from app.models import Role
from app.permissions.registry import DEFAULT_PERMISSIONS
from tests.conftest import assert_error, auth
from tests.test_production import ok

CODE = "orders.export_delivery_note"
URL = "/orders/delivery-note/supplier"


@pytest.fixture
async def gm(make_user):
    return await make_user(Role.GENERAL_MANAGER)


def _set(client, actor, target, level: str):
    return client.put(
        f"/users/{target.id}/features/order_export", json={"level": level}, headers=auth(actor)
    )


async def test_defaults_gm_has_it_supervisor_and_staff_do_not() -> None:
    assert CODE in DEFAULT_PERMISSIONS[Role.GENERAL_MANAGER]
    assert CODE not in DEFAULT_PERMISSIONS[Role.SUPERVISOR]
    assert CODE not in DEFAULT_PERMISSIONS[Role.STAFF]


async def test_supplier_block_needs_the_permission(client, superadmin, gm, make_user) -> None:
    sup = await make_user(Role.SUPERVISOR)
    staff = await make_user(Role.STAFF)
    for user in (superadmin, gm):
        body = ok(await client.get(URL, headers=auth(user)))
        assert set(body) == {
            "name_km",
            "name_en",
            "address_km",
            "address_en",
            "phone",
            "phone_display",
        }
    for user in (sup, staff):
        assert_error(await client.get(URL, headers=auth(user)), 403, "MISSING_PERMISSION")


async def test_grant_chain_gm_to_supervisor_to_staff(client, gm, make_user) -> None:
    sup = await make_user(Role.SUPERVISOR, created_by=gm.id)
    staff = await make_user(Role.STAFF, created_by=sup.id)
    # The supervisor can't pass on what they don't hold.
    assert_error(await _set(client, sup, staff, "full"), 403, "PERMISSION_NOT_HELD")
    ok(await _set(client, gm, sup, "full"))
    ok(await client.get(URL, headers=auth(sup)))
    # Now they can, to their own staff.
    ok(await _set(client, sup, staff, "full"))
    ok(await client.get(URL, headers=auth(staff)))
    ok(await _set(client, sup, staff, "off"))
    assert_error(await client.get(URL, headers=auth(staff)), 403, "MISSING_PERMISSION")
