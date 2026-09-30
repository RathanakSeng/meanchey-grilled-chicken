"""Production access: the Record level, per-endpoint permissions, defaults and backfill."""

import pytest
from sqlalchemy import delete, select

from app.bootstrap import bootstrap
from app.models import AuditLog, Permission, Role, UserPermission
from app.permissions import registry
from app.permissions.features import current_level
from tests.conftest import assert_error, auth

PRODUCTION = registry.FEATURES_BY_CODE["production"]
FULL = {"production.view", "production.create", "production.update"}
# production.delete (cancel) is general-manager only and outside the feature levels.
ALL = FULL | {"production.delete"}


async def _me_perms(client, user) -> set[str]:
    return {p for p in (await client.get("/auth/me", headers=auth(user))).json()["permissions"]}


async def _set_level(client, actor, target, level: str) -> None:
    r = await client.put(
        f"/users/{target.id}/features/production", json={"level": level}, headers=auth(actor)
    )
    assert r.status_code == 200, r.text
    assert r.json()["current_level"] == level


# --- Registry and levels -------------------------------------------------------------------------


def test_production_levels() -> None:
    assert [level for level, _ in PRODUCTION.levels] == ["off", "view", "record", "full"]
    assert PRODUCTION.level_map["record"] == {"production.view", "production.create"}
    assert PRODUCTION.level_map["full"] == FULL
    assert PRODUCTION.menu == "workstation"
    assert PRODUCTION.applies_to == (Role.GENERAL_MANAGER, Role.SUPERVISOR, Role.STAFF)
    delete = registry.PERMISSIONS[[p.code for p in registry.PERMISSIONS].index("production.delete")]
    assert delete.assignable_to == (Role.GENERAL_MANAGER,)
    # Existing features keep off / view / full.
    for code in ("suppliers", "customers", "staff_management"):
        levels = [level for level, _ in registry.FEATURES_BY_CODE[code].levels]
        assert levels == ["off", "view", "full"]


@pytest.mark.parametrize(
    ("held", "expected"),
    [
        (set(), "off"),
        ({"production.view"}, "view"),
        ({"production.view", "production.create"}, "record"),
        (FULL, "full"),
        # A supervisor holding the four grants from before cancel became GM-only: still "full",
        # because production.delete no longer counts for their role (filtered at read time).
        (ALL, "full"),
        ({"production.view", "production.update"}, "custom"),
        ({"production.create"}, "custom"),
        # production.delete is outside the feature, so it doesn't make a level "custom".
        ({"production.view", "production.create", "production.delete"}, "record"),
    ],
)
def test_record_level_detection(held, expected) -> None:
    assert current_level(PRODUCTION, held) == expected


def _feature(levels) -> registry.FeatureDef:
    return registry.FeatureDef(
        code="x",
        menu="workstation",
        name_en="x",
        name_km="x",
        description_en="x",
        description_km="x",
        applies_to=(Role.STAFF,),
        levels=levels,
    )


def test_registry_accepts_record_only_in_order() -> None:
    registry.validate_features(features=[_feature((("off", ()), ("record", ("production.view",))))])
    for bad in (
        (("off", ()), ("full", ("production.view",)), ("record", ("production.view",))),
        (("off", ()), ("record", ("production.view",)), ("record", ("production.view",))),
        (("off", ()), ("edit", ("production.view",))),
    ):
        with pytest.raises(registry.FeatureRegistryError, match="invalid levels"):
            registry.validate_features(features=[_feature(bad)])


async def test_access_tab_lists_four_levels_for_production(client, make_user) -> None:
    gm = await make_user(Role.GENERAL_MANAGER)
    staff = await make_user(Role.STAFF)
    r = await client.get(f"/users/{staff.id}/features", headers=auth(gm))
    features = {f["code"]: f for m in r.json()["menus"] for f in m["features"]}
    assert features["production"]["levels"] == ["off", "view", "record", "full"]
    assert features["production"]["current_level"] == "off"
    assert features["suppliers"]["levels"] == ["off", "view", "full"]


async def test_gm_sets_every_level_and_me_reflects_it(client, make_user) -> None:
    gm = await make_user(Role.GENERAL_MANAGER)
    staff = await make_user(Role.STAFF)
    expected = {
        "view": {"production.view"},
        "record": {"production.view", "production.create"},
        "full": FULL,
        "off": set(),
    }
    for level, codes in expected.items():
        await _set_level(client, gm, staff, level)
        assert (await _me_perms(client, staff)) & ALL == codes


async def test_defaults(client, make_user) -> None:
    gm = await make_user(Role.GENERAL_MANAGER)
    sup = await make_user(Role.SUPERVISOR)
    staff = await make_user(Role.STAFF)
    assert (await _me_perms(client, gm)) >= ALL
    assert (await _me_perms(client, sup)) & ALL == FULL
    assert not (await _me_perms(client, staff)) & ALL


async def test_backfill_grants_production_to_existing_managers_only(session, make_user) -> None:
    gm = await make_user(Role.GENERAL_MANAGER)
    sup = await make_user(Role.SUPERVISOR)
    staff = await make_user(Role.STAFF)
    # As before this feature was deployed.
    await session.execute(delete(UserPermission).where(UserPermission.permission_code.in_(ALL)))
    await session.execute(delete(Permission).where(Permission.code.in_(ALL)))
    await session.execute(delete(AuditLog))
    await session.commit()

    await bootstrap(session)

    async def held(user) -> set[str]:
        return set(
            await session.scalars(
                select(UserPermission.permission_code).where(
                    UserPermission.user_id == user.id, UserPermission.permission_code.in_(ALL)
                )
            )
        )

    assert await held(gm) == ALL
    assert await held(sup) == FULL
    assert await held(staff) == set()


# --- Endpoint permissions ------------------------------------------------------------------------


@pytest.fixture
async def world(client, make_user) -> dict:
    gm = await make_user(Role.GENERAL_MANAGER)
    r = await client.post("/suppliers", json={"name": "Sokha Farm"}, headers=auth(gm))
    supplier = r.json()
    r = await client.post(
        "/production",
        json={"supplier_id": supplier["id"], "weight_kg": "20", "quantity": 8},
        headers=auth(gm),
    )
    return {"gm": gm, "supplier": supplier, "batch": r.json()}


async def _staff_at(client, make_user, gm, level: str):
    staff = await make_user(Role.STAFF)
    if level != "off":
        await _set_level(client, gm, staff, level)
    return staff


async def test_off_sees_nothing(client, make_user, world) -> None:
    staff = await _staff_at(client, make_user, world["gm"], "off")
    batch_id = world["batch"]["id"]
    for url in ("/production", "/production/stats", f"/production/{batch_id}"):
        assert_error(await client.get(url, headers=auth(staff)), 403, "MISSING_PERMISSION")


async def test_view_only_reads_but_cannot_record(client, make_user, world) -> None:
    staff = await _staff_at(client, make_user, world["gm"], "view")
    batch = world["batch"]
    h = auth(staff)
    for url in ("/production", "/production/stats", f"/production/{batch['id']}"):
        assert (await client.get(url, headers=h)).status_code == 200
    assert_error(await client.post("/production", json={}, headers=h), 403, "MISSING_PERMISSION")
    assert_error(
        await client.get("/production/supplier-options", headers=h), 403, "MISSING_PERMISSION"
    )
    r = await client.patch(
        f"/production/{batch['id']}/raw-material", json={"version": 1, "quantity": 2}, headers=h
    )
    assert_error(r, 403, "MISSING_PERMISSION")


async def test_record_can_fill_and_finish_but_not_reopen_or_cancel(
    client, make_user, world
) -> None:
    staff = await _staff_at(client, make_user, world["gm"], "record")
    h = auth(staff)

    # Supplier options work without any Suppliers permission.
    assert "suppliers.view" not in await _me_perms(client, staff)
    r = await client.get("/production/supplier-options", headers=h)
    assert [o["name"] for o in r.json()] == ["Sokha Farm"]

    r = await client.post(
        "/production",
        json={"supplier_id": world["supplier"]["id"], "weight_kg": "12.5", "quantity": 5},
        headers=h,
    )
    assert r.status_code == 201, r.text
    batch = r.json()
    base = f"/production/{batch['id']}"

    async def post(path: str, body: dict, status: int = 200) -> dict:
        r = await client.post(f"{base}{path}", json=body, headers=h)
        assert r.status_code == status, r.text
        return r.json()

    batch = await post("/raw-material/finish", {"version": batch["version"]})
    r = await client.patch(
        f"{base}/produced",
        json={
            "version": batch["version"],
            "wings_kg": "2",
            "thighs_kg": "3",
            "marinade_g": "100",
            "byproducts": {c: "0.1" for c in ("gizzard", "liver", "heart", "head")},
        },
        headers=h,
    )
    batch = r.json()
    batch = await post("/produced/finish", {"version": batch["version"]})

    # No reopen, no cancel.
    r = await client.post(
        f"{base}/raw-material/reopen", json={"version": batch["version"]}, headers=h
    )
    assert_error(r, 403, "MISSING_PERMISSION")
    r = await client.post(
        f"{base}/cancel", json={"version": batch["version"], "reason": "x"}, headers=h
    )
    assert_error(r, 403, "MISSING_PERMISSION")

    # The GM sets the packaging plan (staff don't hold production_plan.*).
    gm = auth(world["gm"])
    plan = f"/production-plans/{batch['id']}"
    body = {"version": batch["version"], "expected_big": 5, "expected_small": 0}
    r = await client.patch(plan, json=body, headers=gm)
    assert r.status_code == 200, r.text
    r = await client.post(f"{plan}/confirm", json={"version": r.json()["version"]}, headers=gm)
    assert r.status_code == 200, r.text
    batch = (await client.get(base, headers=h)).json()

    r = await client.patch(
        f"{base}/standardize",
        json={
            "version": batch["version"],
            "big_packages": 5,
            "small_packages": 0,
            "rejected_wings": 0,
            "rejected_thighs": 0,
            "byproducts": {
                c: {"carry_kg": "0.1", "rejected_kg": "0"}
                for c in ("gizzard", "liver", "heart", "head")
            },
        },
        headers=h,
    )
    batch = r.json()
    batch = await post("/standardize/finish", {"version": batch["version"]})
    assert batch["status"] == "completed"
    assert batch["standardize"]["finished_by"]["id"] == str(staff.id)


async def _finish_step_1(client, actor, batch) -> dict:
    r = await client.post(
        f"/production/{batch['id']}/raw-material/finish",
        json={"version": batch["version"]},
        headers=auth(actor),
    )
    assert r.status_code == 200, r.text
    return r.json()


def _cancel(client, actor, batch):
    return client.post(
        f"/production/{batch['id']}/cancel",
        json={"version": batch["version"], "reason": "Test"},
        headers=auth(actor),
    )


async def test_full_can_edit_finished_steps_but_not_cancel(client, make_user, world) -> None:
    staff = await _staff_at(client, make_user, world["gm"], "full")
    sup = await make_user(Role.SUPERVISOR)  # defaults: Full access
    batch = await _finish_step_1(client, world["gm"], world["batch"])
    r = await client.post(
        f"/production/{batch['id']}/raw-material/reopen",
        json={"version": batch["version"]},
        headers=auth(staff),
    )
    assert r.status_code == 200, r.text
    batch = r.json()
    for user in (staff, sup):
        assert_error(await _cancel(client, user, batch), 403, "MISSING_PERMISSION")


async def test_old_supervisor_cancel_grant_has_no_effect(client, session, make_user, world) -> None:
    """Supervisors granted production.delete before it became GM-only keep the row only."""
    sup = await make_user(Role.SUPERVISOR, perms=sorted(ALL))
    assert "production.delete" not in await _me_perms(client, sup)
    r = await client.get(f"/users/{sup.id}/features", headers=auth(world["gm"]))
    levels = {f["code"]: f["current_level"] for m in r.json()["menus"] for f in m["features"]}
    assert levels["production"] == "full"
    assert_error(await _cancel(client, sup, world["batch"]), 403, "MISSING_PERMISSION")


async def test_gm_and_superadmin_can_cancel(client, make_user, superadmin, world) -> None:
    r = await _cancel(client, world["gm"], world["batch"])
    assert r.status_code == 200, r.text
    r = await client.post("/production", json={}, headers=auth(superadmin))
    assert r.status_code == 201, r.text
    r = await _cancel(client, superadmin, r.json())
    assert r.status_code == 200, r.text
