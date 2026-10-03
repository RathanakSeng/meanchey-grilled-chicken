"""The superadmin can do everything the general manager can.

Walks every `/api/v1` route and method in the app's OpenAPI schema: wherever the general manager
gets anything but 403, the superadmin must not get 403 either. New endpoints are covered
automatically, so a guard like `require_role(Role.GENERAL_MANAGER)` (without the superadmin) or a
service check on `role == general_manager` fails here with the route's name.

Requests carry an empty JSON body unless BODIES has a valid one. FastAPI runs the auth guards
(`require_permission`, `require_role`) before validating the body, so guard-level 403s always
show; BODIES covers routes whose permission / scope check happens in the service.
"""

import re
import uuid

import pytest
from sqlalchemy import update

from app.main import app
from app.models import Role, User
from tests.conftest import auth

PREFIX = "/api/v1"
# Valid bodies for routes that decide access in the service (after body validation).
BODIES: dict[tuple[str, str], dict] = {
    ("POST", "/users/{user_id}/role"): {"role": "supervisor"},
    ("PUT", "/users/{user_id}/features/{feature}"): {"level": "view"},
    ("PATCH", "/users/{user_id}"): {"full_name": "Target Staff"},
    ("PATCH", "/production-plans/{batch_id}"): {"version": 1, "expected_big": 1},
    ("PUT", "/settings/role-limits/{role}"): {"max_active": 10},
    ("POST", "/inventory/items/{item_code}/set"): {"count": 1, "reason": "Superset check"},
}


@pytest.fixture
async def world(client, session, superadmin, make_user) -> dict:
    gm = await make_user(Role.GENERAL_MANAGER)
    target = await make_user(Role.STAFF)  # someone both can manage
    h = auth(gm)
    supplier = (await client.post("/suppliers", json={"name": "Sokha Farm"}, headers=h)).json()
    customer = (await client.post("/customers", json={"name": "Dara Shop"}, headers=h)).json()
    batch = (
        await client.post(
            "/production",
            json={"supplier_id": supplier["id"], "weight_kg": "10", "quantity": 4},
            headers=h,
        )
    ).json()
    order = (
        await client.post(
            "/orders",
            json={
                "customer_id": customer["id"],
                "boxes": [{"color": "white", "lines": [{"item_code": "packs_big", "count": 1}]}],
            },
            headers=h,
        )
    ).json()
    return {
        "gm": gm,
        "superadmin": superadmin,
        "order_id": order["id"],
        "user_id": str(target.id),
        "suppliers": supplier["id"],
        "customers": customer["id"],
        "batch_id": batch["id"],
    }


def _routes() -> list[tuple[str, str]]:
    return [
        (method.upper(), path.removeprefix(PREFIX))
        for path, ops in app.openapi()["paths"].items()
        if path.startswith(PREFIX)
        for method in ops
    ]


def _fill(path: str, world: dict) -> str:
    url = path.replace("{user_id}", world["user_id"])
    url = url.replace("{batch_id}", world["batch_id"]).replace("{step}", "raw-material")
    url = url.replace("{code}", "suppliers.view").replace("{feature}", "suppliers")
    url = url.replace("{role}", "staff").replace("{item_code}", "packs_big")
    url = url.replace("{order_id}", world["order_id"])
    # Someone else's (or no) notification: 404 for both, never 403.
    url = url.replace("{notification_id}", str(uuid.uuid4()))
    if "{partner_id}" in url:
        url = url.replace("{partner_id}", world[url.split("/")[1]])
    assert not re.search(r"\{\w+\}", url), f"superset test doesn't know how to fill {path}"
    return url


async def _call(client, method: str, url: str, body: dict | None, user: User):
    kwargs = {"headers": auth(user)}
    if method != "GET":
        kwargs["json"] = body or {}
    return await client.request(method, url, **kwargs)


async def test_superadmin_is_never_forbidden_where_the_gm_is_allowed(
    client, session, world
) -> None:
    gm, sa = world["gm"], world["superadmin"]
    checked, failures = [], []
    for method, path in _routes():
        url = _fill(path, world)
        body = BODIES.get((method, path))
        # Earlier calls (e.g. /me/reset-password) must not lock either account out.
        await session.execute(
            update(User)
            .where(User.id.in_([gm.id, sa.id]))
            .values(must_change_password=False, is_active=True, locked_until=None)
        )
        await session.commit()
        as_gm = await _call(client, method, url, body, gm)
        if as_gm.status_code == 403:
            continue
        as_sa = await _call(client, method, url, body, sa)
        checked.append(f"{method} {path}")
        if as_sa.status_code == 403:
            failures.append(f"{method} {path}: GM {as_gm.status_code}, superadmin 403 {as_sa.text}")

    assert not failures, "superadmin forbidden where the GM is allowed:\n" + "\n".join(failures)
    # The walk really covered the app (GM-accessible routes of every area).
    for route in (
        "GET /users/{user_id}",
        "POST /users/{user_id}/role",
        "PUT /users/{user_id}/features/{feature}",
        "GET /audit-logs",
        "POST /suppliers",
        "POST /production/{batch_id}/cancel",
        "GET /production-plans",
        "PATCH /production-plans/{batch_id}",
        "GET /notifications",
        "GET /orders/{order_id}",
        "POST /orders/{order_id}/returns/review",
    ):
        assert route in checked, route
