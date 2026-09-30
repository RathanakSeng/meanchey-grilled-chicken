"""Feature levels for the general manager: set by the superadmin only."""

import pytest
from sqlalchemy import select

from app.models import AuditLog, Role
from app.permissions import registry
from tests.conftest import assert_error, auth

GM_ONLY = {"users.delete", "users.reset_password", "permissions.grant", "production.delete"}


async def _me_perms(client, user) -> set[str]:
    return set((await client.get("/auth/me", headers=auth(user))).json()["permissions"])


async def _features(client, actor, target) -> dict[str, dict]:
    r = await client.get(f"/users/{target.id}/features", headers=auth(actor))
    assert r.status_code == 200, r.text
    return {f["code"]: f for m in r.json()["menus"] for f in m["features"]}


def _set(client, actor, target, feature, level):
    return client.put(
        f"/users/{target.id}/features/{feature}", json={"level": level}, headers=auth(actor)
    )


def test_every_feature_applies_to_the_gm() -> None:
    for code in ("suppliers", "customers", "production", "staff_management"):
        assert Role.GENERAL_MANAGER in registry.FEATURES_BY_CODE[code].applies_to
    registry.validate_features()
    # GM-only powers stay outside the levels.
    feature_codes = set().union(*(f.codes for f in registry.FEATURES))
    assert not GM_ONLY & feature_codes


async def test_superadmin_sees_the_gm_at_full_access(client, superadmin, make_user) -> None:
    gm = await make_user(Role.GENERAL_MANAGER)
    r = await client.get(f"/users/{gm.id}/features", headers=auth(superadmin))
    menus = [(m["menu"], [f["code"] for f in m["features"]]) for m in r.json()["menus"]]
    assert menus == [
        ("workstation", ["suppliers", "customers", "production", "production_plan"]),
        ("settings", ["staff_management"]),  # Staff access is for supervisors only
    ]
    features = await _features(client, superadmin, gm)
    assert {f["current_level"] for f in features.values()} == {"full"}
    assert all(f["can_edit"] for f in features.values())
    assert [lv["level"] for lv in features["production"]["levels"]] == [
        "off",
        "view",
        "record",
        "full",
    ]
    # The superadmin may give any level.
    assert all(lv["allowed"] for f in features.values() for lv in f["levels"])


@pytest.mark.parametrize(
    ("feature", "level", "expected"),
    [
        ("suppliers", "view", {"suppliers.view"}),
        ("customers", "off", set()),
        ("production", "record", {"production.view", "production.create"}),
        ("staff_management", "view", {"users.view"}),
    ],
)
async def test_superadmin_sets_gm_levels(
    client, session, superadmin, make_user, feature, level, expected
) -> None:
    gm = await make_user(Role.GENERAL_MANAGER)
    r = await _set(client, superadmin, gm, feature, level)
    assert r.status_code == 200, r.text
    assert r.json()["current_level"] == level

    perms = await _me_perms(client, gm)
    codes = registry.FEATURES_BY_CODE[feature].codes
    assert perms & codes == expected
    # GM-only powers are untouched by level changes.
    assert perms >= GM_ONLY

    log = await session.scalar(select(AuditLog).where(AuditLog.action == "feature.set"))
    assert log.actor_id == superadmin.id and log.target_user_id == gm.id
    assert log.details["feature"] == feature and log.details["to"] == level
    # Made by the superadmin, so the GM's audit log leaves it out.
    r = await client.get("/audit-logs?action=feature.set", headers=auth(gm))
    assert r.json()["items"] == []


async def test_staff_management_off_takes_the_users_list_away(
    client, superadmin, make_user
) -> None:
    gm = await make_user(Role.GENERAL_MANAGER)
    assert (await _set(client, superadmin, gm, "staff_management", "off")).status_code == 200
    assert_error(await client.get("/users", headers=auth(gm)), 403, "MISSING_PERMISSION")
    # Deactivating users is GM-only and outside the feature: still held.
    assert "users.delete" in await _me_perms(client, gm)


async def test_gm_cannot_manage_its_own_access(client, make_user) -> None:
    gm = await make_user(Role.GENERAL_MANAGER)
    h = auth(gm)
    assert_error(await client.get(f"/users/{gm.id}/features", headers=h), 403, "FORBIDDEN_SCOPE")
    assert_error(await _set(client, gm, gm, "suppliers", "off"), 403, "FORBIDDEN_SCOPE")
    assert_error(await client.get(f"/users/{gm.id}/permissions", headers=h), 403, "FORBIDDEN_ROLE")
    assert_error(
        await client.delete(f"/users/{gm.id}/permissions/users.view", headers=h),
        403,
        "FORBIDDEN_ROLE",
    )


async def test_gm_still_manages_supervisors_and_staff(client, make_user) -> None:
    gm = await make_user(Role.GENERAL_MANAGER)
    sup = await make_user(Role.SUPERVISOR)
    features = await _features(client, gm, sup)
    assert set(features) == {
        "suppliers",
        "customers",
        "production",
        "production_plan",
        "staff_management",
        "staff_access",
    }
    assert (await _set(client, gm, sup, "production", "record")).status_code == 200
