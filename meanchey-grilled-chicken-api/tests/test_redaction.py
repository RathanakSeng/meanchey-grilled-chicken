"""The superadmin is invisible to everyone else (services/redaction.py).

The sweep walks the app's own route list (from its OpenAPI schema), so a new GET endpoint is
covered automatically.
"""

import re
import uuid

import pytest
from httpx import Response
from sqlalchemy import select, update

from app.main import app
from app.models import AttendanceRequest, AuditLog, Order, OrderBox, Role, User, utcnow
from tests.conftest import auth
from tests.test_business_info import image

SWEEP_PREFIX = "/api/v1"


SCHEDULE = {
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
    "workplace_ids": "all",
}
HOLIDAY = {
    "name_km": "ភ្ជុំបិណ្ឌ",
    "name_en": "Pchum Ben",
    "start_date": "2026-09-21",
    "end_date": "2026-09-23",
    "scope": "all",
}
FUTURE_HOLIDAY = {
    "name_km": "ចូលឆ្នាំ",
    "name_en": "Khmer New Year",
    "start_date": "2099-04-14",
    "end_date": "2099-04-16",
    "scope": "all",
}


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
    # The audit log is off for a GM until the superadmin allows it.
    r = await client.put(
        f"/users/{gm_id}/features/audit_log", json={"level": "view"}, headers=auth(superadmin)
    )
    assert r.status_code == 200, r.text
    # So is Attendance scheduling (employees' own schedules, holiday exceptions).
    r = await client.put(
        f"/users/{gm_id}/features/attendance_scheduling",
        json={"level": "full"},
        headers=auth(superadmin),
    )
    assert r.status_code == 200, r.text
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
    # The supervisor gets plan access (and the alerts); the superadmin finishes step 2 of a
    # second batch (alerts naming it as the actor) and sets and confirms its plan.
    await client.put(
        f"/users/{sup_id}/features/production_plan",
        json={"level": "full"},
        headers=auth(superadmin),
    )
    planned = await post(
        "/production", {"supplier_id": supplier["id"], "weight_kg": "25.5", "quantity": 10}
    )
    planned = await post(f"/production/{planned['id']}/raw-material/finish", {"version": 1})
    r = await client.patch(
        f"/production/{planned['id']}/produced",
        json={
            "version": planned["version"],
            "wings_kg": "4",
            "thighs_kg": "6",
            "marinade_g": "300",
            "byproducts": {c: "0.5" for c in ("gizzard", "liver", "heart", "head")},
        },
        headers=auth(superadmin),
    )
    planned = await post(
        f"/production/{planned['id']}/produced/finish", {"version": r.json()["version"]}
    )
    r = await client.patch(
        f"/production-plans/{planned['id']}",
        json={"version": planned["version"], "expected_big": 7, "expected_small": 5},
        headers=auth(superadmin),
    )
    plan = await post(
        f"/production-plans/{planned['id']}/confirm", {"version": r.json()["version"]}
    )
    await client.patch(
        f"/suppliers/{supplier['id']}", json={"location": "Kandal"}, headers=auth(superadmin)
    )
    # Detailed grants and a feature change, both by the superadmin.
    await client.put(f"/users/{staff_id}/permissions/customers.view", headers=auth(superadmin))
    await client.put(
        f"/users/{staff_id}/features/suppliers", json={"level": "view"}, headers=auth(superadmin)
    )
    # A role limit the superadmin changed (settings.role_limit_update, updated_by).
    r = await client.put(
        "/settings/role-limits/staff", json={"max_active": 12}, headers=auth(superadmin)
    )
    assert r.status_code == 200, r.text
    # A material the superadmin created, stocked and archived; and stock it added to another.
    glue = await post("/inventory/materials", {"name_km": "កាវ", "name_en": "Glue", "unit": "g"})
    await post(f"/inventory/materials/{glue['id']}/add", {"quantity": "10"})
    await post(f"/inventory/materials/{glue['id']}/archive")
    string = next(
        m
        for m in (await client.get("/inventory/materials", headers=auth(superadmin))).json()
        if m["name_en"] == "String"
    )
    await post(f"/inventory/materials/{string['id']}/add", {"quantity": "1"})
    # An icon the superadmin uploaded (material.update, updated_by).
    r = await client.put(
        f"/inventory/materials/{string['id']}/icon",
        files={"file": ("icon.png", image("PNG", 40, 40), "image/png")},
        headers=auth(superadmin),
    )
    assert r.status_code == 200, r.text
    # Orders the superadmin created (one cancelled by it), with the staff member as driver.
    order_body = {
        "customer_id": customer["id"],
        "driver_id": staff_id,
        "boxes": [{"color": "white", "lines": [{"item_code": "packs_big", "count": 1}]}],
    }
    order = await post("/orders", order_body)
    cancelled = await post("/orders", order_body)
    await post(f"/orders/{cancelled['id']}/cancel", {"version": 1, "reason": "Customer cancelled"})
    # Preparations the superadmin created and finished (alerting the GM) and cancelled.
    prepared = await post("/preparations", {"type": "packaging_material"})
    prepared = (
        await client.patch(
            f"/preparations/{prepared['id']}",
            json={"version": 1, "lines": [{"material_id": string["id"], "quantity": "0.5"}]},
            headers=auth(superadmin),
        )
    ).json()
    prepared = await post(f"/preparations/{prepared['id']}/finish", {"version": 2})
    dropped = await post("/preparations", {"type": "satay_sachet"})
    await post(f"/preparations/{dropped['id']}/cancel", {"version": 1, "reason": "Not needed"})
    # Its step 1 finish above also wrote inventory movements with created_by = the superadmin.
    # Attendance: the superadmin set the workplace, created a second one (created_by), changed
    # the schedule of all (today and an upcoming version: created_by), added a holiday, added a
    # missing record for the staff member and corrected it (updated_by / corrected_by); the
    # supervisor sees the day view.
    workplace = (await client.get("/attendance/workplaces", headers=auth(superadmin))).json()[0]
    r = await client.patch(
        f"/attendance/workplaces/{workplace['id']}",
        json={"latitude": 11.55, "longitude": 104.91, "radius_m": 120},
        headers=auth(superadmin),
    )
    assert r.status_code == 200, r.text
    branch = await post("/attendance/workplaces", {"name": "Branch 2", "radius_m": 200})
    for body in (SCHEDULE, {**SCHEDULE, "effective_from": "2099-01-01", "checkout_window_min": 40}):
        r = await client.put("/attendance/scheduling/shifts", json=body, headers=auth(superadmin))
        assert r.status_code == 200, r.text
    holiday = (await post("/attendance/holidays", HOLIDAY))["holiday"]
    # The superadmin gave the staff member an own schedule (an upcoming version: created_by) and
    # set them to work on a future holiday (created_by).
    r = await client.put(
        "/attendance/scheduling/employees",
        json={
            "user_ids": [staff_id],
            "weekdays": [1, 2, 3, 4, 5, 6],
            "effective_from": "2099-01-01",
        },
        headers=auth(superadmin),
    )
    assert r.status_code == 200, r.text
    future = (await post("/attendance/holidays", FUTURE_HOLIDAY))["holiday"]
    r = await client.put(
        f"/attendance/holidays/{future['id']}/exceptions",
        json={"user_ids": [staff_id], "dates": ["2099-04-14"]},
        headers=auth(superadmin),
    )
    assert r.status_code == 200, r.text
    attendance = await post(
        "/attendance/records",
        {
            "user_id": staff_id,
            "work_date": "2026-10-01",
            "shift_code": "morning",
            "status": "present",
            "check_in_time": "07:05",
            "reason": "Checked in on paper",
        },
    )
    r = await client.patch(
        f"/attendance/records/{attendance['id']}",
        json={"status": "present", "check_in_time": "07:00", "reason": "Fixed the time"},
        headers=auth(superadmin),
    )
    assert r.status_code == 200, r.text
    await client.put(
        f"/users/{sup_id}/features/attendance", json={"level": "view"}, headers=auth(superadmin)
    )
    # Superadmin-targeted audit entries (its own sign-in, a failed one).
    await client.post("/auth/login", json={"username": "superadmin", "password": "wrong"})
    await client.post("/auth/login", json={"username": "superadmin", "password": "superadmin"})
    # A request the superadmin approved (reviewed_by): everyone else reads "System".
    request = AttendanceRequest(
        user_id=uuid.UUID(staff_id),
        year=2026,
        month=9,
        status="approved",
        missing_minutes=90,
        extra_minutes=0,
        absent_minutes=90,
        late_minutes=0,
        balance_minutes=-90,
        requested_salary_cut_minutes=30,
        requested_unpaid_work_minutes=60,
        approved_salary_cut_minutes=90,
        approved_unpaid_work_minutes=0,
        type="both",
        approved_with_changes=True,
        review_comment="Changed",
        reviewed_by=superadmin.id,
        reviewed_at=utcnow(),
    )
    session.add(request)
    await session.flush()
    request_id = str(request.id)
    # An order whose white box the superadmin recorded as not returned at delivery (written
    # directly: the world has no stock to deliver from).
    kept = await post("/orders", order_body)
    await session.execute(
        update(OrderBox)
        .where(OrderBox.order_id == uuid.UUID(kept["id"]))
        .values(
            container_status="not_returned",
            container_reason="Kept by the shop",
            container_recorded_by=superadmin.id,
            container_recorded_at=utcnow(),
        )
    )
    await session.execute(
        update(Order)
        .where(Order.id == uuid.UUID(kept["id"]))
        .values(status="success", delivered_by=superadmin.id, delivered_at=utcnow())
    )
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
        "planned": planned["id"],
        "planned_version": plan["version"],
        "orders": [order["id"], cancelled["id"], kept["id"]],
        "kept_box": kept["boxes"][0]["id"],
        "string": string,
        "preparations": [prepared["id"], dropped["id"]],
        "workplace": workplace["id"],
        "branch": branch["id"],
        "attendance_record": attendance["id"],
        "holiday": holiday["id"],
        "future_holiday": future["id"],
        "request": request_id,
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
    if path.startswith("/production-plans/"):
        return [path.replace("{batch_id}", world["planned"])]
    if "{order_id}" in path:
        return [path.replace("{order_id}", o) for o in world["orders"]]
    if "{item_code}" in path:
        return [path.replace("{item_code}", "chicken")]
    if "{preparation_id}" in path:
        return [path.replace("{preparation_id}", p) for p in world["preparations"]]
    if "{material_id}" in path:
        return [path.replace("{material_id}", world["string"]["id"])]
    if "{batch_id}" in path:
        return [path.replace("{batch_id}", world[k]) for k in ("batch", "planned")]
    if "{workplace_id}" in path:
        return [path.replace("{workplace_id}", world["workplace"])]
    if "{holiday_id}" in path:
        return [path.replace("{holiday_id}", world[k]) for k in ("holiday", "future_holiday")]
    if "{request_id}" in path:
        return [path.replace("{request_id}", world["request"])]
    assert not re.search(r"\{\w+\}", path), f"sweep doesn't know how to fill {path}"
    return [path]


EXTRA_QUERIES = [
    "/users?role=superadmin",
    "/users?role=nope",  # validation error must not list the roles
    "/users?q=super",
    "/audit-logs?page_size=100",
    "/audit-logs?action=permission.grant",
    "/audit-logs?action=auth.login",
    "/production-plans?status=all",
    "/production?waiting_step=3",
    "/notifications?unread_only=true",
    "/inventory/movements?source=production",
    "/inventory/movements?batch_code=PR",
    "/audit-logs?action=inventory.adjust",
    "/orders?status=cancelled",
    "/orders?q=OR-",
    "/audit-logs?action=order.cancel",
    "/inventory/materials?include_archived=true",
    "/inventory/movements?source=material_add",
    "/audit-logs?action=material.create",
    "/preparations?include_cancelled=true",
    "/inventory/movements?source=preparation",
    "/inventory/movements?section=prepared",
    "/audit-logs?action=preparation.finish",
    "/audit-logs?entity_type=preparation",
    "/attendance/day?date=2026-10-01",
    "/audit-logs?action=attendance.correct",
    "/audit-logs?action=attendance.schedule_update",
    "/audit-logs?action=workplace.create",
    "/audit-logs?action=workplace.update",
    "/attendance/workplaces?include_archived=true",
    "/attendance/calendar?year=2026&month=9",
    "/attendance/holidays?year=2026",
    "/audit-logs?action=attendance.holiday_create",
    "/audit-logs?action=attendance.weekdays_update",
    "/attendance/requests",
    "/attendance/requests?status=approved",
    "/attendance/requests?status=no_request",
    "/attendance/requests/me?year=2026",
    "/attendance/settings/requests",
    "/audit-logs?action=attendance.settings_update",
    "/attendance/scheduling/employees",
    "/attendance/scheduling/employees?custom_only=true",
    "/attendance/calendar?year=2099&month=4",
    "/audit-logs?action=attendance.employee_schedule_update",
    "/audit-logs?action=attendance.holiday_exception_create",
]


@pytest.mark.parametrize("viewer_key", ["gm", "sup", "staff"])
async def test_no_response_reveals_the_superadmin(
    client, world, viewer_key, html_documents
) -> None:
    """Delivery notes (`/orders/{id}/document.pdf`) come back as their HTML (`html_documents`),
    so their text is checked too: the orders' creator reads as "System"."""
    viewer = world[viewer_key]
    sa = world["superadmin"]
    urls = [u for path in _get_routes() for u in _fill(path, world)]
    urls += EXTRA_QUERIES + [
        f"/audit-logs?actor_id={sa.id}",
        f"/audit-logs?target_user_id={sa.id}",
        # The month with the record the superadmin added and corrected (corrected_by).
        f"/attendance/users/{world['staff'].id}/summary?year=2026&month=10",
        "/attendance/me/summary?year=2026&month=10",
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
        client.patch(
            f"/production-plans/{world['planned']}",
            json={"version": world["planned_version"], "note": "Checked"},
            headers=auth(viewer),
        ),
        client.post("/notifications/read-all", headers=auth(viewer)),
        client.post(
            f"/inventory/materials/{world['string']['id']}/add",
            json={"quantity": "1"},
            headers=auth(viewer),
        ),
        client.patch(
            f"/inventory/materials/{world['string']['id']}",
            json={"name_en": "String"},
            headers=auth(viewer),
        ),
        client.put(
            f"/inventory/materials/{world['string']['id']}/icon",
            files={"file": ("icon.png", image("PNG", 30, 30), "image/png")},
            headers=auth(viewer),
        ),
        client.post(f"/orders/{world['orders'][0]}/document/send-telegram", headers=auth(viewer)),
        client.post(
            f"/orders/{world['orders'][2]}/boxes/{world['kept_box']}/container-returned",
            headers=auth(viewer),
        ),
        client.patch(
            f"/attendance/records/{world['attendance_record']}",
            json={"status": "present", "check_in_time": "07:00", "reason": "Fixed the time"},
            headers=auth(viewer),
        ),
        client.patch(
            f"/attendance/workplaces/{world['workplace']}",
            json={"radius_m": 120},
            headers=auth(viewer),
        ),
        client.put("/attendance/scheduling/shifts", json=SCHEDULE, headers=auth(viewer)),
        client.patch(
            f"/attendance/holidays/{world['holiday']}",
            json={**HOLIDAY, "note": "Checked"},
            headers=auth(viewer),
        ),
        client.put(
            "/attendance/scheduling/employees",
            json={"user_ids": [str(world["staff"].id)], "shift_codes": ["morning"]},
            headers=auth(viewer),
        ),
        client.put(
            f"/attendance/holidays/{world['future_holiday']}/exceptions",
            json={"user_ids": [str(world["staff"].id)], "dates": ["2099-04-15"]},
            headers=auth(viewer),
        ),
        client.post("/attendance/workplaces", json={"name": "Branch 3"}, headers=auth(viewer)),
        client.post(f"/attendance/workplaces/{world['branch']}/restore", headers=auth(viewer)),
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


async def test_delivery_note_names_the_superadmin_as_system(client, world, html_documents) -> None:
    for key in ("gm", "sup"):
        r = await client.get(f"/orders/{world['orders'][0]}/document.pdf", headers=auth(world[key]))
        assert r.status_code == 200, r.text
        assert "System" in r.text
        _assert_clean(r, world["superadmin"], f"{key} delivery note")


async def test_alerts_and_plans_name_the_superadmin_as_system(client, world) -> None:
    for key in ("gm", "sup"):
        page = (await client.get("/notifications", headers=auth(world[key]))).json()
        # The plan alert; the GM also the preparation alert (preparation.update).
        assert page["total"] == (2 if key == "gm" else 1)
        assert all(item["actor"]["is_system"] is True for item in page["items"])
        plan = (
            await client.get(f"/production-plans/{world['planned']}", headers=auth(world[key]))
        ).json()["plan"]
        assert plan["confirmed_by"]["is_system"] is True
    # Staff get no alerts, only news of their own schedule (set by the superadmin: "System").
    page = (await client.get("/notifications", headers=auth(world["staff"]))).json()
    assert {item["type"] for item in page["items"]} == {
        "attendance.schedule_changed",
        "attendance.holiday_work",
    }
    assert all(item["actor"]["is_system"] is True for item in page["items"])


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

    order = (await client.get(f"/orders/{world['orders'][2]}", headers=auth(gm))).json()
    assert order["boxes"][0]["container_recorded_by"]["is_system"] is True
    order = (
        await client.post(
            f"/orders/{world['orders'][2]}/boxes/{world['kept_box']}/container-returned",
            headers=auth(gm),
        )
    ).json()
    assert order["boxes"][0]["container_status"] == "returned"
    assert order["boxes"][0]["container_recorded_by"]["is_system"] is True

    staff = world["staff"].id
    detail = (
        await client.get(f"/attendance/scheduling/employees/{staff}", headers=auth(gm))
    ).json()
    assert detail["upcoming"][0]["created_by"]["is_system"] is True
    working = (
        await client.get(
            f"/attendance/holidays/{world['future_holiday']}/exceptions", headers=auth(gm)
        )
    ).json()
    assert working["items"][0]["created_by"]["is_system"] is True

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
