"""Inventory history (inventory.history): who sees movements, and the grantor-must-hold rule of
the inventory_history feature (hidden from grantors who don't hold it)."""

import pytest
from sqlalchemy import select

from app.models import AuditLog, Role
from app.permissions.registry import DEFAULT_PERMISSIONS
from tests.conftest import assert_error, auth
from tests.test_production import Api, ok

HISTORY = "inventory.history"


@pytest.fixture
async def gm(make_user):
    return await make_user(Role.GENERAL_MANAGER)


@pytest.fixture
async def supplier(client, gm) -> dict:
    return ok(await client.post("/suppliers", json={"name": "Sokha Farm"}, headers=auth(gm)), 201)


def _set(client, actor, target, level: str):
    return client.put(
        f"/users/{target.id}/features/inventory_history", json={"level": level}, headers=auth(actor)
    )


async def _feature_codes(client, actor, target) -> set[str]:
    r = await client.get(f"/users/{target.id}/features", headers=auth(actor))
    return {f["code"] for m in ok(r)["menus"] for f in m["features"]}


async def _perms(client, user) -> set[str]:
    return set(ok(await client.get("/auth/me", headers=auth(user)))["permissions"])


# --- Defaults and guards -------------------------------------------------------------------------


async def test_off_by_default_and_superadmin_always(client, superadmin, gm, make_user) -> None:
    sup = await make_user(Role.SUPERVISOR)
    for user in (gm, sup):
        assert HISTORY not in await _perms(client, user)
        assert_error(
            await client.get("/inventory/movements", headers=auth(user)), 403, "MISSING_PERMISSION"
        )
    ok(await client.get("/inventory/movements", headers=auth(superadmin)))


async def test_batch_stock_changes_need_history(client, superadmin, gm, supplier) -> None:
    batch = await Api(client, gm).step1(supplier, 10)
    # The GM without history: the batch has no inventory fields at all.
    assert "stock_changes" not in batch and "inventory_tracked" not in batch
    body = ok(await client.get(f"/production/{batch['id']}", headers=auth(gm)))
    assert "stock_changes" not in body and "inventory_tracked" not in body
    # The superadmin sees them.
    body = ok(await client.get(f"/production/{batch['id']}", headers=auth(superadmin)))
    assert body["inventory_tracked"] is True
    assert [c["item_code"] for c in body["stock_changes"]] == ["chicken"]
    # Once granted, the GM sees them too.
    ok(await _set(client, superadmin, gm, "view"))
    body = ok(await client.get(f"/production/{batch['id']}", headers=auth(gm)))
    assert body["stock_changes"][0]["count_delta"] == 10


# --- Grantor must hold ---------------------------------------------------------------------------


async def test_superadmin_sets_it_on_gms_and_supervisors(client, superadmin, gm, make_user):
    sup = await make_user(Role.SUPERVISOR)
    for target in (gm, sup):
        assert "inventory_history" in await _feature_codes(client, superadmin, target)
        r = ok(await _set(client, superadmin, target, "view"))
        assert r["current_level"] == "view"
        assert HISTORY in await _perms(client, target)
        ok(await client.get("/inventory/movements", headers=auth(target)))


async def test_gm_without_it_never_sees_the_option(client, superadmin, gm, make_user) -> None:
    sup = await make_user(Role.SUPERVISOR)
    staff = await make_user(Role.STAFF)
    assert "inventory_history" not in await _feature_codes(client, gm, sup)
    # Not a permission error: it doesn't exist for this GM.
    assert_error(await _set(client, gm, sup, "view"), 404, "FEATURE_NOT_FOUND")
    assert_error(await _set(client, gm, sup, "off"), 404, "FEATURE_NOT_FOUND")
    # Hidden before the target-role check too (staff: it doesn't apply, but the GM can't tell).
    assert_error(await _set(client, gm, staff, "view"), 404, "FEATURE_NOT_FOUND")


async def test_gm_holding_it_gives_it_to_supervisors(client, superadmin, gm, make_user) -> None:
    sup = await make_user(Role.SUPERVISOR)
    ok(await _set(client, superadmin, gm, "view"))
    assert "inventory_history" in await _feature_codes(client, gm, sup)
    assert ok(await _set(client, gm, sup, "view"))["current_level"] == "view"
    ok(await client.get("/inventory/movements", headers=auth(sup)))

    # No cascade: taking it from the GM leaves the supervisor's.
    ok(await _set(client, superadmin, gm, "off"))
    assert HISTORY in await _perms(client, sup)
    # ...but the GM no longer sees the option (or can change it).
    assert "inventory_history" not in await _feature_codes(client, gm, sup)
    assert_error(await _set(client, gm, sup, "off"), 404, "FEATURE_NOT_FOUND")


async def test_supervisors_never_grant_it(client, make_user) -> None:
    sup = await make_user(
        Role.SUPERVISOR, perms=sorted(DEFAULT_PERMISSIONS[Role.SUPERVISOR] | {HISTORY})
    )
    staff = await make_user(Role.STAFF)
    # Applies to GMs and supervisors only: never on staff, the only role a supervisor reaches.
    assert "inventory_history" not in await _feature_codes(client, sup, staff)
    assert_error(await _set(client, sup, staff, "view"), 422, "FEATURE_NOT_APPLICABLE")


async def test_audit_entries_hidden_from_gms_without_it(
    client, session, superadmin, make_user
) -> None:
    gm = await make_user(Role.GENERAL_MANAGER)
    other_gm = await make_user(Role.GENERAL_MANAGER)
    sup = await make_user(Role.SUPERVISOR)
    ok(await _set(client, superadmin, gm, "view"))
    ok(await _set(client, gm, sup, "view"))  # made by the GM: visible in the GM audit log
    ok(
        await client.put(
            f"/users/{sup.id}/features/suppliers", json={"level": "view"}, headers=auth(gm)
        )
    )

    def features_in(r) -> set[str]:
        return {e["details"]["feature"] for e in ok(r)["items"]}

    url = "/audit-logs?action=feature.set"
    assert features_in(await client.get(url, headers=auth(gm))) == {
        "inventory_history",
        "suppliers",
    }
    # Another GM without it: the inventory_history change is left out, the rest stays.
    assert features_in(await client.get(url, headers=auth(other_gm))) == {"suppliers"}
    stored = await session.scalar(
        select(AuditLog).where(
            AuditLog.action == "feature.set",
            AuditLog.target_user_id == sup.id,
            AuditLog.details["feature"].astext == "inventory_history",
        )
    )
    assert stored is not None  # still recorded
