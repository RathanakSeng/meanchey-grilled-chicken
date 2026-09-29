"""Production access: the Record level, per-endpoint permissions, defaults and backfill."""

import pytest
from sqlalchemy import delete, select

from app.bootstrap import bootstrap
from app.models import AuditLog, Permission, Role, UserPermission
from app.permissions import registry
from app.permissions.features import current_level
from tests.conftest import assert_error, auth

PRODUCTION = registry.FEATURES_BY_CODE["production"]
ALL = {"production.view", "production.create", "production.update", "production.delete"}


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
    assert PRODUCTION.level_map["full"] == ALL
    assert PRODUCTION.menu == "workstation"
    assert PRODUCTION.applies_to == (Role.SUPERVISOR, Role.STAFF)
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
        (ALL, "full"),
        ({"production.view", "production.update"}, "custom"),
        ({"production.create"}, "custom"),
        ({"production.view", "production.create", "production.delete"}, "custom"),
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
        "full": ALL,
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
    assert (await _me_perms(client, sup)) >= ALL
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
    assert await held(sup) == ALL
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


async def test_full_can_reopen_and_cancel(client, make_user, world) -> None:
    staff = await _staff_at(client, make_user, world["gm"], "full")
    batch = world["batch"]
    r = await client.post(
        f"/production/{batch['id']}/cancel",
        json={"version": batch["version"], "reason": "Test"},
        headers=auth(staff),
    )
    assert r.status_code == 200, r.text
