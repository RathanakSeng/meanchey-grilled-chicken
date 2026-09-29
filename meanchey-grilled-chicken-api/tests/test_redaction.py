"""The superadmin is invisible to everyone else (services/redaction.py).

The sweep walks the app's own route list (from its OpenAPI schema), so a new GET endpoint is
covered automatically.
"""

import re

import pytest
from httpx import Response
from sqlalchemy import select, update

from app.main import app
from app.models import AuditLog, Role, User
from tests.conftest import auth

SWEEP_PREFIX = "/api/v1"


@pytest.fixture
async def world(client, session, superadmin, make_user) -> dict:
    """Realistic data where the superadmin created, granted and changed things."""

    async def post(path, body=None):
        r = await client.post(path, json=body, headers=auth(superadmin))
        assert r.status_code in (200, 201, 204), r.text
        return r.json() if r.content else None

    gm_body = {
        "role": "general_manager",
        "full_name": "Gina Manager",
        "telegram_username": "gina_gm",
    }
    gm_id = (await post("/users", gm_body))["id"]
    sup_body = {"role": "supervisor", "full_name": "Sam Super", "telegram_username": "sam_sup"}
    sup_id = (await post("/users", sup_body))["id"]
    staff_body = {
        "role": "staff",
        "full_name": "Sok Staff",
        "telegram_username": "sok_staff",
        "position": "Grill cook",
    }
    staff_id = (await post("/users", staff_body))["id"]
    supplier = await post("/suppliers", {"name": "Sokha Farm", "phone": "012345678"})
    customer = await post("/customers", {"name": "Dara Shop"})
    # A production batch the superadmin created and finished step 1 of.
    batch = await post(
        "/production",
        {"supplier_id": supplier["id"], "weight_kg": "25.5", "quantity": 10},
    )
    batch = await post(f"/production/{batch['id']}/raw-material/finish", {"version": 1})
    await client.patch(
        f"/suppliers/{supplier['id']}", json={"location": "Kandal"}, headers=auth(superadmin)
    )
    # Detailed grants and a feature change, both by the superadmin.
    await client.put(f"/users/{staff_id}/permissions/customers.view", headers=auth(superadmin))
    await client.put(
        f"/users/{staff_id}/features/suppliers", json={"level": "view"}, headers=auth(superadmin)
    )
    # Superadmin-targeted audit entries (its own sign-in, a failed one).
    await client.post("/auth/login", json={"username": "superadmin", "password": "wrong"})
    await client.post("/auth/login", json={"username": "superadmin", "password": "superadmin"})
    # Users the sweep acts as: skip the forced first-login password change.
    await session.execute(
        update(User).where(User.role != Role.SUPERADMIN).values(must_change_password=False)
    )
    await session.commit()
    users = {u.id: u for u in await session.scalars(select(User))}
    by_id = {str(k): v for k, v in users.items()}
    return {
        "superadmin": superadmin,
        "gm": by_id[gm_id],
        "sup": by_id[sup_id],
        "staff": by_id[staff_id],
        "supplier": supplier["id"],
        "customer": customer["id"],
        "batch": batch["id"],
        "batch_version": batch["version"],
    }


def _forbidden_strings(superadmin: User) -> list[str]:
    return [str(superadmin.id), "superadmin", superadmin.full_name.lower(), "super admin"]


def _assert_clean(response: Response, superadmin: User, where: str) -> None:
    body = response.text.lower()
    for needle in _forbidden_strings(superadmin):
        assert needle.lower() not in body, f"{where}: response reveals {needle!r}: {response.text}"


def _get_routes() -> list[str]:
    """Every documented GET route of the API (the schema is built even when /docs is off)."""
    return [
        path.removeprefix(SWEEP_PREFIX)
        for path, ops in app.openapi()["paths"].items()
        if "get" in ops and path.startswith(SWEEP_PREFIX)
    ]


def _fill(path: str, world: dict) -> list[str]:
    """Every concrete URL for a route template, including the superadmin's own id."""
    if "{user_id}" in path:
        ids = [world[k].id for k in ("superadmin", "gm", "sup", "staff")]
        return [path.replace("{user_id}", str(i)) for i in ids]
    if "{partner_id}" in path:
        pid = world["supplier"] if path.startswith("/suppliers") else world["customer"]
        return [path.replace("{partner_id}", pid)]
    if "{batch_id}" in path:
        return [path.replace("{batch_id}", world["batch"])]
    assert not re.search(r"\{\w+\}", path), f"sweep doesn't know how to fill {path}"
    return [path]


EXTRA_QUERIES = [
    "/users?role=superadmin",
    "/users?role=nope",  # validation error must not list the roles
    "/users?q=super",
    "/audit-logs?page_size=100",
    "/audit-logs?action=permission.grant",
    "/audit-logs?action=auth.login",
]


@pytest.mark.parametrize("viewer_key", ["gm", "sup", "staff"])
async def test_no_response_reveals_the_superadmin(client, world, viewer_key) -> None:
    viewer = world[viewer_key]
    sa = world["superadmin"]
    urls = [u for path in _get_routes() for u in _fill(path, world)]
    urls += EXTRA_QUERIES + [
        f"/audit-logs?actor_id={sa.id}",
        f"/audit-logs?target_user_id={sa.id}",
    ]
    assert "/auth/me" in urls and "/audit-logs" in urls  # the sweep really covers the app
    for url in urls:
        r = await client.get(url, headers=auth(viewer))
        _assert_clean(r, sa, f"{viewer_key} GET {url}")

    # Mutations that return records the superadmin touched.
    partner_calls = [
        client.patch(
            f"/suppliers/{world['supplier']}", json={"name": "Sokha Farm 2"}, headers=auth(viewer)
        ),
        client.post(f"/customers/{world['customer']}/deactivate", headers=auth(viewer)),
        client.patch(
            f"/production/{world['batch']}/produced",
            json={"version": world["batch_version"], "wings_kg": "5"},
            headers=auth(viewer),
        ),
        client.patch(f"/users/{world['staff'].id}", json={"phone": "012"}, headers=auth(viewer)),
        client.patch(f"/users/{sa.id}", json={"full_name": "x"}, headers=auth(viewer)),
        client.post(f"/users/{sa.id}/reset-password", headers=auth(viewer)),
        client.post(f"/users/{sa.id}/deactivate", headers=auth(viewer)),
        client.put(
            f"/users/{sa.id}/features/suppliers", json={"level": "view"}, headers=auth(viewer)
        ),
        client.put(f"/users/{sa.id}/permissions/users.view", headers=auth(viewer)),
        client.post(
            "/users",
            json={"role": "superadmin", "full_name": "x", "telegram_username": "someone_x"},
            headers=auth(viewer),
        ),
    ]
    for call in partner_calls:
        r = await call
        _assert_clean(r, sa, f"{viewer_key} mutation {r.request.method} {r.request.url}")


async def test_lookup_by_id_is_not_found(client, world) -> None:
    for viewer_key in ("gm", "sup"):
        r = await client.get(f"/users/{world['superadmin'].id}", headers=auth(world[viewer_key]))
        assert r.status_code == 404
        assert r.json()["error"]["code"] == "USER_NOT_FOUND"


async def test_references_become_system(client, world) -> None:
    gm = world["gm"]
    me = (await client.get("/auth/me", headers=auth(gm))).json()
    system = {"id": None, "full_name": "System", "role": None, "telegram_username": None}
    assert me["user"]["created_by"] == {**system, "is_system": True}

    supplier = (await client.get(f"/suppliers/{world['supplier']}", headers=auth(gm))).json()
    assert supplier["created_by"]["is_system"] is True
    assert supplier["updated_by"]["is_system"] is True

    # The superadmin sees itself.
    sa = world["superadmin"]
    supplier = (await client.get(f"/suppliers/{world['supplier']}", headers=auth(sa))).json()
    assert supplier["created_by"]["id"] == str(sa.id)
    assert supplier["created_by"]["is_system"] is False


async def test_audit_log_for_the_gm(client, session, world) -> None:
    gm, sa = world["gm"], world["superadmin"]
    items = (await client.get("/audit-logs?page_size=100", headers=auth(gm))).json()["items"]
    actions = {i["action"] for i in items}
    assert not {"permission.grant", "permission.revoke"} & actions
    # Nothing the superadmin did (it created users, suppliers, changed access)...
    assert not {"user.create", "supplier.create", "supplier.update", "feature.set"} & actions
    assert all(i["actor"] is None or not i["actor"]["is_system"] for i in items)
    assert all(i["target"] is None or i["target"]["id"] is not None for i in items)
    # ...but entries with no actor (e.g. failed sign-ins) would stay.

    # What the GM does shows up.
    staff = world["staff"]
    r = await client.put(
        f"/users/{staff.id}/features/customers", json={"level": "full"}, headers=auth(gm)
    )
    assert r.status_code == 200, r.text
    items = (await client.get("/audit-logs?page_size=100", headers=auth(gm))).json()["items"]
    assert [i["action"] for i in items if i["action"] == "feature.set"] == ["feature.set"]

    # The superadmin still sees everything.
    all_items = (await client.get("/audit-logs?page_size=100", headers=auth(sa))).json()["items"]
    all_actions = {i["action"] for i in all_items}
    assert {"permission.grant", "auth.login", "auth.login_failed"} <= all_actions
    hidden = await session.scalar(select(AuditLog).where(AuditLog.target_user_id == sa.id))
    assert hidden is not None

    for param in ("actor_id", "target_user_id"):
        r = await client.get(f"/audit-logs?{param}={sa.id}", headers=auth(gm))
        assert r.json()["total"] == 0


async def test_validation_errors_do_not_list_roles(client, world) -> None:
    r = await client.get("/users?role=nope", headers=auth(world["gm"]))
    assert r.status_code == 422
    assert "general_manager" not in r.text


async def test_superadmin_is_not_hidden_from_itself(client, world) -> None:
    sa = world["superadmin"]
    me = (await client.get("/auth/me", headers=auth(sa))).json()
    assert me["user"]["role"] == "superadmin"
    items = (await client.get("/audit-logs", headers=auth(sa))).json()["items"]
    assert any(i["actor"] and i["actor"]["role"] == "superadmin" for i in items)


async def test_hidden_when_no_viewer_is_known() -> None:
    """Redaction fails closed: without a recorded viewer the superadmin is hidden."""
    from app.schemas.common import UserRef

    ref = UserRef(id=None, full_name="Real Name", role=Role.SUPERADMIN)
    assert ref.model_dump() == {
        "id": None,
        "full_name": "System",
        "role": None,
        "telegram_username": None,
        "is_system": True,
    }
