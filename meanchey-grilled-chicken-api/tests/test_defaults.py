from sqlalchemy import select

from app.models import Permission, Role
from app.permissions import registry
from app.permissions.sync import sync_registry
from tests.conftest import auth

ALL_PHASE1 = {
    "users.view",
    "users.create",
    "users.update",
    "users.delete",
    "users.reset_password",
    "permissions.grant",
}
PARTNERS = {
    f"{entity}.{action}"
    for entity in ("suppliers", "customers")
    for action in ("view", "create", "update", "delete")
}
PRODUCTION = {f"production.{a}" for a in ("view", "create", "update", "delete")}
PLAN = {"production_plan.view", "production_plan.manage"}


async def _create(client, actor, role: str, username: str) -> dict:
    body = {"role": role, "full_name": username, "telegram_username": username}
    if role == "staff":
        body["position"] = "worker"
    r = await client.post("/users", json=body, headers=auth(actor))
    assert r.status_code == 201, r.text
    return r.json()


async def _perms_of(client, superadmin, user_id) -> set[str]:
    """Stored grants, read through the superadmin-only detailed permission view."""
    r = await client.get(f"/users/{user_id}/permissions", headers=auth(superadmin))
    return {p["code"] for m in r.json()["modules"] for p in m["permissions"] if p["granted"]}


async def test_gm_gets_all_phase1_partner_and_production_permissions(client, superadmin) -> None:
    gm = await _create(client, superadmin, "general_manager", "default_gm")
    assert await _perms_of(client, superadmin, gm["id"]) == (
        ALL_PHASE1 | PARTNERS | PRODUCTION | PLAN
    )


async def test_supervisor_defaults(client, superadmin, make_user) -> None:
    """Every feature at full access; supervisors never get users.delete or permissions.grant."""
    gm = await make_user(Role.GENERAL_MANAGER)
    sup = await _create(client, gm, "supervisor", "default_sup")
    assert await _perms_of(client, superadmin, sup["id"]) == {
        "users.view",
        "users.create",
        "users.update",
        *PARTNERS,
        *(PRODUCTION - {"production.delete"}),  # cancelling batches is GM-only
        # No production plan: Off by default, the GM decides who plans and gets the alerts.
    }


async def test_supervisor_defaults_limited_to_creator_permissions(
    client, superadmin, make_user
) -> None:
    gm = await make_user(Role.GENERAL_MANAGER, perms=["users.view", "users.create"])
    sup = await _create(client, gm, "supervisor", "limited_sup")
    assert await _perms_of(client, superadmin, sup["id"]) == {"users.view", "users.create"}


async def test_staff_has_no_permissions(client, superadmin, make_user) -> None:
    gm = await make_user(Role.GENERAL_MANAGER)
    staff = await _create(client, gm, "staff", "default_staff")
    assert await _perms_of(client, superadmin, staff["id"]) == set()


async def test_registry_sync_marks_removed_permissions_inactive(session, monkeypatch) -> None:
    extra = registry.PermissionDef(
        code="demo.view",
        module="demo",
        name_en="Demo",
        name_km="សាកល្បង",
        description_en="Demo",
        description_km="សាកល្បង",
        assignable_to=(Role.STAFF,),
    )
    monkeypatch.setattr("app.permissions.sync.PERMISSIONS", [*registry.PERMISSIONS, extra])
    await sync_registry(session)
    await session.commit()
    assert (await session.get(Permission, "demo.view")).is_active is True

    monkeypatch.setattr("app.permissions.sync.PERMISSIONS", registry.PERMISSIONS)
    await sync_registry(session)
    await session.commit()
    row = await session.scalar(select(Permission).where(Permission.code == "demo.view"))
    assert row is not None and row.is_active is False
