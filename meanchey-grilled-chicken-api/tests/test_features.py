"""Feature access levels (Off / View only / Full access) over detailed permissions."""

import pytest
from sqlalchemy import select

from app.models import AuditLog, Role, UserPermission
from app.permissions import registry
from app.permissions.features import current_level
from app.permissions.registry import FEATURES_BY_CODE
from tests.conftest import assert_error, auth

SUPPLIERS = FEATURES_BY_CODE["suppliers"]
STAFF_MGMT = FEATURES_BY_CODE["staff_management"]
SUPPLIER_FULL = {"suppliers.view", "suppliers.create", "suppliers.update", "suppliers.delete"}


def _set(client, actor, target, feature, level):
    return client.put(
        f"/users/{target.id}/features/{feature}", json={"level": level}, headers=auth(actor)
    )


async def _features(client, actor, target) -> dict[str, dict]:
    r = await client.get(f"/users/{target.id}/features", headers=auth(actor))
    assert r.status_code == 200, r.text
    return {f["code"]: f for m in r.json()["menus"] for f in m["features"]}


async def _stored(session, user) -> set[str]:
    return set(
        await session.scalars(
            select(UserPermission.permission_code).where(UserPermission.user_id == user.id)
        )
    )


async def _me(client, user) -> dict:
    return (await client.get("/auth/me", headers=auth(user))).json()


# --- Level mapping ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("held", "expected"),
    [
        (set(), "off"),
        ({"suppliers.view"}, "view"),
        (SUPPLIER_FULL, "full"),
        ({"suppliers.view", "suppliers.create"}, "custom"),
        ({"suppliers.create"}, "custom"),
        # Codes of other features don't matter.
        ({"suppliers.view", "customers.create", "users.view"}, "view"),
    ],
)
def test_current_level(held, expected) -> None:
    assert current_level(SUPPLIERS, held) == expected


def test_levels_are_exact_sets() -> None:
    levels = SUPPLIERS.level_map
    assert levels == {
        "off": frozenset(),
        "view": frozenset({"suppliers.view"}),
        "full": frozenset(SUPPLIER_FULL),
    }
    # Supervisors never deactivate users, so full staff management has no users.delete.
    assert STAFF_MGMT.level_map["full"] == {"users.view", "users.create", "users.update"}


def test_grant_and_reset_password_belong_to_no_feature() -> None:
    codes = set().union(*(f.codes for f in registry.FEATURES))
    assert "permissions.grant" not in codes
    assert "users.reset_password" not in codes


def test_menus() -> None:
    assert registry.MENUS == ("workstation", "settings")
    # "production" is reserved for a future feature; the suppliers/customers section is Workstation.
    assert all(f.menu != "production" for f in registry.FEATURES)
    assert {f.code: f.menu for f in registry.FEATURES if f.menu == "workstation"} == {
        "suppliers": "workstation",
        "customers": "workstation",
        "production": "workstation",
        "production_plan": "workstation",
    }


def test_startup_validation_rejects_unknown_menu() -> None:
    bad = registry.FeatureDef(
        code="old_menu",
        menu="production",  # type: ignore[arg-type]
        name_en="x",
        name_km="x",
        description_en="x",
        description_km="x",
        applies_to=(Role.STAFF,),
        levels=(("off", ()), ("view", ("suppliers.view",))),
    )
    with pytest.raises(registry.FeatureRegistryError, match="unknown menu"):
        registry.validate_features(features=[bad])


def test_startup_validation_rejects_unknown_permission() -> None:
    bad = registry.FeatureDef(
        code="ghost",
        menu="workstation",
        name_en="x",
        name_km="x",
        description_en="x",
        description_km="x",
        applies_to=(Role.STAFF,),
        levels=(("off", ()), ("view", ("ghost.view",))),
    )
    with pytest.raises(registry.FeatureRegistryError, match="unknown permission"):
        registry.validate_features(features=[*registry.FEATURES, bad])


def test_startup_validation_rejects_non_assignable_permission() -> None:
    bad = registry.FeatureDef(
        code="staff_users",
        menu="settings",
        name_en="x",
        name_km="x",
        description_en="x",
        description_km="x",
        applies_to=(Role.STAFF,),  # users.view can't be held by staff
        levels=(("off", ()), ("view", ("users.view",))),
    )
    with pytest.raises(registry.FeatureRegistryError, match="not assignable"):
        registry.validate_features(features=[*registry.FEATURES, bad])


def test_startup_validation_requires_off_first() -> None:
    bad = registry.FeatureDef(
        code="no_off",
        menu="workstation",
        name_en="x",
        name_km="x",
        description_en="x",
        description_km="x",
        applies_to=(Role.STAFF,),
        levels=(("view", ("suppliers.view",)),),
    )
    with pytest.raises(registry.FeatureRegistryError, match="off"):
        registry.validate_features(features=[bad])


# --- Reading levels -----------------------------------------------------------------------------


async def test_gm_sees_staff_features_off_by_default(client, make_user) -> None:
    gm = await make_user(Role.GENERAL_MANAGER)
    staff = await make_user(Role.STAFF)
    r = await client.get(f"/users/{staff.id}/features", headers=auth(gm))
    body = r.json()
    assert [m["menu"] for m in body["menus"]] == ["workstation"]
    features = body["menus"][0]["features"]
    assert [f["code"] for f in features] == ["suppliers", "customers", "production"]
    assert all(f["current_level"] == "off" and f["can_edit"] for f in features)
    assert features[0]["levels"] == ["off", "view", "full"]
    assert features[0]["name_km"] == "អ្នកផ្គត់ផ្គង់"


async def test_gm_sees_supervisor_features_full_by_default(client, make_user) -> None:
    gm = await make_user(Role.GENERAL_MANAGER)
    sup = await make_user(Role.SUPERVISOR)
    r = await client.get(f"/users/{sup.id}/features", headers=auth(gm))
    menus = [(m["menu"], [f["code"] for f in m["features"]]) for m in r.json()["menus"]]
    # Workstation first, then settings.
    assert menus == [
        ("workstation", ["suppliers", "customers", "production", "production_plan"]),
        ("settings", ["staff_management"]),
    ]
    levels = {code: f["current_level"] for code, f in (await _features(client, gm, sup)).items()}
    # Everything at full access, except the production plan (Off by default).
    assert levels.pop("production_plan") == "off"
    assert set(levels.values()) == {"full"}


async def test_superadmin_can_use_features_too(client, superadmin, make_user) -> None:
    staff = await make_user(Role.STAFF)
    assert (await _set(client, superadmin, staff, "customers", "view")).status_code == 200
    assert (await _features(client, superadmin, staff))["customers"]["current_level"] == "view"


async def test_can_edit_false_for_inactive_target(client, make_user) -> None:
    gm = await make_user(Role.GENERAL_MANAGER)
    staff = await make_user(Role.STAFF, is_active=False)
    assert not any(f["can_edit"] for f in (await _features(client, gm, staff)).values())


# --- Setting levels -----------------------------------------------------------------------------


async def test_level_transitions_change_only_the_feature(client, session, make_user) -> None:
    gm = await make_user(Role.GENERAL_MANAGER)
    staff = await make_user(Role.STAFF, perms=["customers.view"])

    async def level_is(expected: str, stored: set[str]) -> None:
        assert (await _features(client, gm, staff))["suppliers"]["current_level"] == expected
        assert await _stored(session, staff) == stored | {"customers.view"}

    r = await _set(client, gm, staff, "suppliers", "view")  # off -> view
    assert r.status_code == 200 and r.json()["current_level"] == "view"
    await level_is("view", {"suppliers.view"})
    await _set(client, gm, staff, "suppliers", "full")  # view -> full
    await level_is("full", SUPPLIER_FULL)
    await _set(client, gm, staff, "suppliers", "off")  # full -> off
    await level_is("off", set())


async def test_custom_is_overwritten(client, session, make_user) -> None:
    gm = await make_user(Role.GENERAL_MANAGER)
    staff = await make_user(Role.STAFF, perms=["suppliers.view", "suppliers.update"])
    assert (await _features(client, gm, staff))["suppliers"]["current_level"] == "custom"
    await _set(client, gm, staff, "suppliers", "view")
    assert await _stored(session, staff) == {"suppliers.view"}


async def test_one_audit_entry_per_change_and_repeat_is_noop(client, session, make_user) -> None:
    gm = await make_user(Role.GENERAL_MANAGER)
    staff = await make_user(Role.STAFF)
    await _set(client, gm, staff, "suppliers", "view")
    await _set(client, gm, staff, "suppliers", "full")
    r = await _set(client, gm, staff, "suppliers", "full")  # no-op
    assert r.status_code == 200

    logs = list(
        await session.scalars(
            select(AuditLog).where(AuditLog.target_user_id == staff.id).order_by(AuditLog.id)
        )
    )
    assert [log.action for log in logs] == ["feature.set", "feature.set"]
    assert logs[0].actor_id == gm.id
    assert logs[0].details == {
        "feature": "suppliers",
        "from": "off",
        "to": "view",
        "added": ["suppliers.view"],
        "removed": [],
    }
    assert logs[1].details["from"] == "view"
    assert logs[1].details["added"] == ["suppliers.create", "suppliers.delete", "suppliers.update"]


async def test_staff_view_only_then_full(client, make_user) -> None:
    """Done-when scenario: View only -> read-only list; Full access -> can add."""
    gm = await make_user(Role.GENERAL_MANAGER)
    staff = await make_user(Role.STAFF)
    await _set(client, gm, staff, "suppliers", "view")
    assert (await client.get("/suppliers", headers=auth(staff))).status_code == 200
    assert_error(
        await client.post("/suppliers", json={"name": "A"}, headers=auth(staff)),
        403,
        "MISSING_PERMISSION",
    )
    await _set(client, gm, staff, "suppliers", "full")
    assert (
        await client.post("/suppliers", json={"name": "A"}, headers=auth(staff))
    ).status_code == 201


async def test_gm_turns_off_supervisor_staff_management(client, make_user) -> None:
    gm = await make_user(Role.GENERAL_MANAGER)
    sup = await make_user(Role.SUPERVISOR)
    assert "users.view" in (await _me(client, sup))["permissions"]
    assert (await _set(client, gm, sup, "staff_management", "off")).status_code == 200
    me = await _me(client, sup)
    assert not {"users.view", "users.create", "users.update"} & set(me["permissions"])
    assert_error(await client.get("/users", headers=auth(sup)), 403, "MISSING_PERMISSION")


# --- Guards -------------------------------------------------------------------------------------


async def test_supervisor_cannot_use_feature_endpoints(client, make_user) -> None:
    sup = await make_user(Role.SUPERVISOR)
    staff = await make_user(Role.STAFF)
    assert_error(
        await client.get(f"/users/{staff.id}/features", headers=auth(sup)),
        403,
        "MISSING_PERMISSION",
    )
    assert_error(await _set(client, sup, staff, "suppliers", "view"), 403, "MISSING_PERMISSION")


async def test_check_order(client, superadmin, make_user) -> None:
    gm = await make_user(Role.GENERAL_MANAGER)
    staff = await make_user(Role.STAFF)
    inactive = await make_user(Role.STAFF, is_active=False)
    # Scope comes first, even with a bad feature and level.
    assert_error(await _set(client, gm, gm, "nope", "nope"), 403, "FORBIDDEN_SCOPE")
    # The hidden account is simply not found.
    assert_error(await _set(client, gm, superadmin, "suppliers", "view"), 404, "USER_NOT_FOUND")
    assert_error(await _set(client, gm, staff, "nope", "nope"), 404, "FEATURE_NOT_FOUND")
    assert_error(
        await _set(client, gm, staff, "staff_management", "nope"), 422, "FEATURE_NOT_APPLICABLE"
    )
    assert_error(await _set(client, gm, staff, "suppliers", "nope"), 422, "VALIDATION_ERROR")
    assert_error(await _set(client, gm, inactive, "suppliers", "view"), 409, "USER_INACTIVE")


async def test_gm_sets_any_level_without_holding_it(client, session, make_user) -> None:
    """The Access layer is the GM's: own feature permissions don't limit what they can give."""
    gm = await make_user(Role.GENERAL_MANAGER, perms=["permissions.grant"])
    staff = await make_user(Role.STAFF)
    sup = await make_user(Role.SUPERVISOR, perms=[])
    features = await _features(client, gm, staff)
    assert all(f["can_edit"] for f in features.values())

    assert (await _set(client, gm, staff, "suppliers", "full")).status_code == 200
    assert (await _set(client, gm, staff, "customers", "view")).status_code == 200
    assert (await _set(client, gm, sup, "staff_management", "full")).status_code == 200
    assert await _stored(session, staff) == SUPPLIER_FULL | {"customers.view"}
    assert "users.create" in (await _me(client, sup))["permissions"]


async def test_managing_access_needs_permissions_grant(client, make_user) -> None:
    gm = await make_user(Role.GENERAL_MANAGER, perms=["suppliers.view"])  # grant revoked
    staff = await make_user(Role.STAFF)
    assert_error(await _set(client, gm, staff, "suppliers", "view"), 403, "MISSING_PERMISSION")


async def test_me_reports_can_manage_features(client, superadmin, make_user) -> None:
    gm = await make_user(Role.GENERAL_MANAGER)
    sup = await make_user(Role.SUPERVISOR)
    staff = await make_user(Role.STAFF)
    assert (await _me(client, superadmin))["can_manage_features"] is True
    assert (await _me(client, gm))["can_manage_features"] is True
    assert (await _me(client, sup))["can_manage_features"] is False
    assert (await _me(client, staff))["can_manage_features"] is False
