"""Workplace access levels: off / view / record (edit existing) / full (create, delete, restore,
default) against every workplace endpoint; level detection; migration 0024 keeps Full at Full."""

import asyncio
import uuid
from datetime import UTC, datetime

import pytest
from alembic import command

from app.models import Role
from tests.conftest import assert_error, auth, make_workplace
from tests.test_migration_step_dates import _alembic, _run

VIEW = "attendance.workplace_view"
UPDATE = "attendance.workplace_update"
MANAGE = "attendance.workplace_manage"


async def _set_level(client, superadmin, gm, level: str) -> None:
    r = await client.put(
        f"/users/{gm.id}/features/attendance_workplace",
        json={"level": level},
        headers=auth(superadmin),
    )
    assert r.status_code == 200, r.text


async def _level(client, superadmin, gm) -> str:
    menus = (await client.get(f"/users/{gm.id}/features", headers=auth(superadmin))).json()
    features = {f["code"]: f for m in menus["menus"] for f in m["features"]}
    return features["attendance_workplace"]["current_level"]


@pytest.mark.parametrize("level", ["off", "view", "record", "full"])
async def test_each_level_against_each_endpoint(
    client, session, superadmin, make_user, level
) -> None:
    gm = await make_user(Role.GENERAL_MANAGER)
    await _set_level(client, superadmin, gm, level)
    assert await _level(client, superadmin, gm) == level
    h = auth(gm)
    can_see, can_edit, can_manage = level != "off", level in ("record", "full"), level == "full"

    branch = await make_workplace(session)
    url = f"/attendance/workplaces/{branch.id}"

    def check(r, allowed: bool, status: int = 200) -> None:
        if allowed:
            assert r.status_code == status, r.text
        else:
            assert_error(r, 403, "MISSING_PERMISSION")

    check(await client.get("/attendance/workplaces", headers=h), can_see)
    check(await client.get(url, headers=h), can_see)
    # The GM also holds users.view, which opens the options (the user form's select).
    check(await client.get("/attendance/workplace-options", headers=h), True)

    # Edit an existing workplace: name, address, pin, radius.
    edit = {
        "name": "Branch North",
        "address": "St 2",
        "latitude": 11.57,
        "longitude": 104.9,
        "radius_m": 180,
    }
    r = await client.patch(url, json=edit, headers=h)
    check(r, can_edit)
    if can_edit:
        out = r.json()
        assert (out["name"], out["address"], out["radius_m"]) == ("Branch North", "St 2", 180)
        assert (out["latitude"], out["longitude"]) == (11.57, 104.9)

    # Changing the default needs Full; with Record nothing is saved (radius included).
    r = await client.patch(url, json={"radius_m": 250, "is_default": True}, headers=h)
    check(r, can_manage)
    if can_edit and not can_manage:
        assert r.json()["error"]["details"]["required"] == [MANAGE]
    await session.refresh(branch)
    assert branch.is_default is can_manage
    assert branch.radius_m == (250 if can_manage else 180 if can_edit else 100)

    # Create, delete, restore: Full only.
    r = await client.post("/attendance/workplaces", json={"name": "New one"}, headers=h)
    check(r, can_manage, 201)
    extra = await make_workplace(session, "Extra", metres_north=9000)
    r = await client.delete(f"/attendance/workplaces/{extra.id}", headers=h)
    check(r, can_manage)
    archived = await make_workplace(session, "Old", metres_north=12000)
    archived.is_active = False
    archived.archived_at = datetime.now(UTC)
    await session.commit()
    r = await client.post(f"/attendance/workplaces/{archived.id}/restore", headers=h)
    check(r, can_manage)


async def test_level_detection(client, superadmin, make_user) -> None:
    for perms, level in (
        ([VIEW], "view"),
        ([VIEW, UPDATE], "record"),
        ([VIEW, UPDATE, MANAGE], "full"),
        ([VIEW, MANAGE], "custom"),  # Full before the split, not migrated
        ([UPDATE], "custom"),
    ):
        gm = await make_user(Role.GENERAL_MANAGER, perms=perms)
        assert await _level(client, superadmin, gm) == level, perms


async def test_record_is_only_for_the_superadmin_to_set(client, superadmin, make_user) -> None:
    """GM-only feature: a GM can't set it on another GM; the superadmin can do everything."""
    gm = await make_user(Role.GENERAL_MANAGER)
    other = await make_user(Role.GENERAL_MANAGER)
    r = await client.put(
        f"/users/{other.id}/features/attendance_workplace",
        json={"level": "record"},
        headers=auth(gm),
    )
    assert r.status_code == 403, r.text
    created = await client.post(
        "/attendance/workplaces",
        json={"name": "Super", "latitude": 11.6, "longitude": 104.9},
        headers=auth(superadmin),
    )
    assert created.status_code == 201, created.text
    url = f"/attendance/workplaces/{created.json()['id']}"
    r = await client.patch(
        url, json={"radius_m": 300, "is_default": True}, headers=auth(superadmin)
    )
    assert r.status_code == 200, r.text
    assert r.json()["is_default"] is True


def test_migration_keeps_full_at_full() -> None:
    full, view, gone = (uuid.uuid4() for _ in range(3))
    rows = [(full, True, (VIEW, MANAGE)), (view, True, (VIEW,)), (gone, False, (VIEW, MANAGE))]
    _alembic(command.downgrade, "0023")
    try:
        asyncio.run(
            _run(
                "INSERT INTO users (id, role, full_name, telegram_username, password_hash, "
                "is_active) VALUES "
                + ", ".join(
                    f"('{uid}', 'general_manager', 'Mig {n}', 'mig_wprec_{n}', 'x', {active})"
                    for n, (uid, active, _) in enumerate(rows)
                ),
                "INSERT INTO user_permissions (user_id, permission_code, granted_by) VALUES "
                + ", ".join(
                    f"('{uid}', '{code}', NULL)" for uid, _, codes in rows for code in codes
                ),
            )
        )
    finally:
        _alembic(command.upgrade, "head")

    async def held() -> dict[uuid.UUID, set[str]]:
        out: dict[uuid.UUID, set[str]] = {}
        for uid, code in await _run(
            "SELECT user_id, permission_code FROM user_permissions WHERE user_id = ANY(:ids)",
            ids=[r[0] for r in rows],
        ):
            out.setdefault(uid, set()).add(code)
        return out

    async def logs() -> list:
        return await _run(
            "SELECT actor_id, target_user_id, details FROM audit_logs "
            "WHERE action = 'permission.grant' AND target_user_id = ANY(:ids) ORDER BY id",
            ids=[r[0] for r in rows],
        )

    try:
        after = asyncio.run(held())
        assert after[full] == after[gone] == {VIEW, UPDATE, MANAGE}
        assert after[view] == {VIEW}
        entries = asyncio.run(logs())
        assert {target for _, target, _ in entries} == {full, gone}
        for actor, _, details in entries:
            assert actor is None
            assert details == {"permission": UPDATE, "source": "default_change"}
        # Downgrade drops the new grants; upgrading again restores them (logged again).
        _alembic(command.downgrade, "0023")
        assert asyncio.run(held())[full] == {VIEW, MANAGE}
        _alembic(command.upgrade, "head")
        assert asyncio.run(held()) == after
    finally:
        asyncio.run(
            _run(
                "DELETE FROM audit_logs WHERE target_user_id = ANY(:ids)",
                "DELETE FROM users WHERE telegram_username LIKE 'mig_wprec_%'",
                ids=[r[0] for r in rows],
            )
        )
