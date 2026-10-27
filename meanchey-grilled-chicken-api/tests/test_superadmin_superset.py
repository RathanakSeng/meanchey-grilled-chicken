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
from app.permissions.registry import DEFAULT_PERMISSIONS
from tests.conftest import auth

PREFIX = "/api/v1"
# Valid bodies for routes that decide access in the service (after body validation).
HOLIDAY = {
    "name_km": "បុណ្យ",
    "name_en": "Superset day",
    "start_date": "2099-12-25",
    "end_date": "2099-12-26",
    "scope": "all",
}
BODIES: dict[tuple[str, str], dict] = {
    ("POST", "/users/{user_id}/role"): {"role": "supervisor"},
    ("PUT", "/users/{user_id}/features/{feature}"): {"level": "view"},
    ("PATCH", "/users/{user_id}"): {"full_name": "Target Staff"},
    ("PATCH", "/production-plans/{batch_id}"): {"version": 1, "expected_big": 1},
    ("PUT", "/settings/role-limits/{role}"): {"max_active": 10},
    ("POST", "/inventory/items/{item_code}/set"): {"count": 1, "reason": "Superset check"},
    ("PUT", "/settings/business"): {"name_km": "ហាង", "name_en": "Shop"},
    ("POST", "/inventory/materials"): {"name_km": "កាវ", "name_en": "Glue", "unit": "g"},
    ("PATCH", "/inventory/materials/{material_id}"): {"name_en": "String"},
    ("POST", "/inventory/materials/{material_id}/add"): {"quantity": "1"},
    ("POST", "/inventory/materials/{material_id}/remove"): {"quantity": "0.5", "reason": "Test"},
    ("POST", "/preparations"): {"type": "satay_sachet"},
    # No packs in stock: 409 INVENTORY_INSUFFICIENT for both, never 403.
    ("POST", "/inventory/clears/preview"): {"lines": [{"item_code": "packs_big", "quantity": "1"}]},
    ("POST", "/inventory/clears"): {
        "lines": [{"item_code": "packs_big", "quantity": "1"}],
        "reason": "Superset",
    },
    ("PATCH", "/preparations/{preparation_id}"): {"version": 1, "note": "Superset"},
    ("POST", "/preparations/{preparation_id}/finish"): {"version": 1},
    ("POST", "/preparations/{preparation_id}/reopen"): {"version": 1},
    ("POST", "/preparations/{preparation_id}/cancel"): {"version": 1, "reason": "Superset"},
    ("PATCH", "/attendance/records/{record_id}"): {"status": "absent", "reason": "Superset"},
    ("POST", "/attendance/requests/{request_id}/reject"): {"reason": "Superset"},
    ("PUT", "/attendance/settings/requests"): {"request_deadline_day": 7},
    ("PATCH", "/attendance/workplaces/{workplace_id}"): {"radius_m": 150},
    ("POST", "/attendance/workplaces"): {"name": "Superset"},
    ("PUT", "/attendance/scheduling/weekdays"): {
        "workplace_ids": "all",
        "weekdays": [1, 2, 3, 4, 5, 6, 7],
    },
    ("POST", "/attendance/holidays"): HOLIDAY,
    ("PATCH", "/attendance/holidays/{holiday_id}"): HOLIDAY,
    ("POST", "/attendance/holidays/copy"): {"from_year": 2099, "to_year": 2100},
    ("PUT", "/attendance/scheduling/employees"): {"user_ids": [], "weekdays": [1, 2, 3]},
    ("POST", "/attendance/scheduling/employees/reset"): {"user_ids": []},
    ("PUT", "/attendance/holidays/{holiday_id}/exceptions"): {
        "user_ids": [],
        "dates": ["2099-12-25"],
    },
    ("PUT", "/attendance/scheduling/shifts"): {
        "workplace_ids": "all",
        "shifts": [
            {
                "code": "morning",
                "name_km": "វេនព្រឹក",
                "name_en": "Morning shift",
                "start_time": "07:00",
                "end_time": "12:00",
            },
            {
                "code": "afternoon",
                "name_km": "វេនរសៀល",
                "name_en": "Afternoon shift",
                "start_time": "13:00",
                "end_time": "15:00",
            },
        ],
        "open_before_min": 30,
        "absent_after_min": 45,
        "checkout_window_min": 59,
        "reminders_enabled": True,
        "count_early_checkin": True,
        "count_overtime": True,
    },
}


@pytest.fixture
async def world(client, session, superadmin, make_user) -> dict:
    # With Business info, the audit log and the attendance workplace / shifts (off by default),
    # so their routes are compared too.
    gm = await make_user(
        Role.GENERAL_MANAGER,
        perms=sorted(
            DEFAULT_PERMISSIONS[Role.GENERAL_MANAGER]
            | {
                "settings.business_info",
                "audit.view",
                "attendance.workplace_update",
                "attendance.workplace_manage",
                "attendance.scheduling",
            }
        ),
    )
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
    materials = (await client.get("/inventory/materials", headers=h)).json()
    preparation = (
        await client.post("/preparations", json={"type": "satay_sachet"}, headers=h)
    ).json()
    record = (
        await client.post(
            "/attendance/records",
            json={
                "user_id": str(target.id),
                "work_date": "2026-10-01",
                "shift_code": "morning",
                "status": "present",
                "check_in_time": "07:00",
                "reason": "Superset",
            },
            headers=h,
        )
    ).json()
    workplace = (await client.get("/attendance/workplaces", headers=h)).json()[0]
    holiday = (await client.post("/attendance/holidays", json=HOLIDAY, headers=h)).json()
    upcoming = (
        await client.put(
            "/attendance/scheduling/weekdays",
            json={
                "workplace_ids": "all",
                "weekdays": [1, 2, 3, 4, 5],
                "effective_from": "2099-01-01",
            },
            headers=h,
        )
    ).json()
    working = (
        await client.put(
            f"/attendance/holidays/{holiday['holiday']['id']}/exceptions",
            json={"user_ids": [str(target.id)], "dates": ["2099-12-25"]},
            headers=h,
        )
    ).json()
    # Every POST /attendance/records after the first answers 409 (exists): never 403.
    return {
        "exception_id": working["items"][0]["id"],
        "record_id": record["id"],
        "workplace_id": workplace["id"],
        "holiday_id": holiday["holiday"]["id"],
        "version_id": upcoming["scheduling"]["workplaces"][0]["upcoming"][0]["id"],
        "record_body": {
            "user_id": str(target.id),
            "work_date": "2026-10-01",
            "shift_code": "morning",
            "status": "absent",
            "reason": "Superset",
        },
        "preparation_id": preparation["id"],
        "material_id": next(m["id"] for m in materials if m["name_en"] == "String"),
        "gm": gm,
        "superadmin": superadmin,
        "order_id": order["id"],
        "box_id": order["boxes"][0]["id"],
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
    url = url.replace("{box_id}", world["box_id"])
    url = url.replace("{material_id}", world["material_id"])
    url = url.replace("{preparation_id}", world["preparation_id"])
    url = url.replace("{record_id}", world["record_id"])
    url = url.replace("{workplace_id}", world["workplace_id"])
    url = url.replace("{holiday_id}", world["holiday_id"])
    url = url.replace("{version_id}", world["version_id"])
    url = url.replace("{exception_id}", world["exception_id"])
    # No such clear: 404 for both, never 403.
    url = url.replace("{clear_id}", str(uuid.uuid4()))
    # Someone else's (or no) request: 404 for both, never 403.
    url = url.replace("{request_id}", str(uuid.uuid4()))
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
        if (method, path) == ("POST", "/attendance/records"):
            body = world["record_body"]
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
        "POST /orders/{order_id}/boxes/{box_id}/container-returned",
        "GET /orders/{order_id}/document.pdf",
        "POST /orders/{order_id}/document/send-telegram",
        "GET /settings/business",
        "PUT /settings/business",
        "PUT /settings/business/logo",
        "GET /settings/business/preview.pdf",
        "GET /inventory/materials",
        "POST /inventory/materials",
        "PATCH /inventory/materials/{material_id}",
        "POST /inventory/materials/{material_id}/archive",
        "POST /inventory/materials/{material_id}/restore",
        "POST /inventory/materials/{material_id}/add",
        "POST /inventory/materials/{material_id}/remove",
        "GET /inventory/materials/{material_id}/icon",
        "PUT /inventory/materials/{material_id}/icon",
        "DELETE /inventory/materials/{material_id}/icon",
        "POST /inventory/clears/preview",
        "POST /inventory/clears",
        "GET /inventory/clears",
        "GET /inventory/clears/{clear_id}",
        "GET /preparations",
        "GET /preparations/stats",
        "GET /preparations/material-options",
        "POST /preparations",
        "GET /preparations/{preparation_id}",
        "PATCH /preparations/{preparation_id}",
        "POST /preparations/{preparation_id}/finish",
        "POST /preparations/{preparation_id}/reopen",
        "POST /preparations/{preparation_id}/cancel",
        "GET /attendance/day",
        "GET /attendance/users/{user_id}/summary",
        "PATCH /attendance/records/{record_id}",
        "POST /attendance/records",
        "GET /attendance/workplaces",
        "GET /attendance/workplace-options",
        "POST /attendance/workplaces",
        "GET /attendance/workplaces/{workplace_id}",
        "PATCH /attendance/workplaces/{workplace_id}",
        "DELETE /attendance/workplaces/{workplace_id}",
        "POST /attendance/workplaces/{workplace_id}/restore",
        "GET /attendance/scheduling",
        "PUT /attendance/scheduling/weekdays",
        "PUT /attendance/scheduling/shifts",
        "DELETE /attendance/scheduling/versions/{version_id}",
        "GET /attendance/calendar",
        "GET /attendance/holidays",
        "POST /attendance/holidays",
        "POST /attendance/holidays/copy",
        "GET /attendance/holidays/{holiday_id}",
        "GET /attendance/scheduling/employees",
        "GET /attendance/scheduling/employees/{user_id}",
        "PUT /attendance/scheduling/employees",
        "POST /attendance/scheduling/employees/reset",
        "DELETE /attendance/scheduling/employees/{user_id}/versions/{version_id}",
        "GET /attendance/holidays/{holiday_id}/exceptions",
        "PUT /attendance/holidays/{holiday_id}/exceptions",
        "DELETE /attendance/holidays/{holiday_id}/exceptions/{exception_id}",
        "GET /attendance/requests",
        "GET /attendance/requests/{request_id}",
        "POST /attendance/requests/{request_id}/approve",
        "POST /attendance/requests/{request_id}/reject",
        "PATCH /attendance/holidays/{holiday_id}",
        "DELETE /attendance/holidays/{holiday_id}",
    ):
        assert route in checked, route
