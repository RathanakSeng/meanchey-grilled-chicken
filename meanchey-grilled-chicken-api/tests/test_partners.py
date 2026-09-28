"""Suppliers and customers: every test runs against both lists."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.models import AuditLog, Customer, Role, Supplier
from app.services import partner_service
from tests.conftest import assert_error, auth

KINDS = [
    pytest.param(("suppliers", "supplier", Supplier, "SUPPLIER_NOT_FOUND"), id="suppliers"),
    pytest.param(("customers", "customer", Customer, "CUSTOMER_NOT_FOUND"), id="customers"),
]
MISSING_ID = "00000000-0000-0000-0000-000000000000"


@pytest.fixture(params=KINDS)
def kind(request):
    return request.param


@pytest.fixture
async def sup(make_user):
    """Supervisor with the default permissions, which include all partner permissions."""
    return await make_user(Role.SUPERVISOR)


async def _create(client, actor, prefix, **body):
    body.setdefault("name", "Sok Dara")
    return await client.post(f"/{prefix}", json=body, headers=auth(actor))


async def _created(client, actor, prefix, **body) -> dict:
    r = await _create(client, actor, prefix, **body)
    assert r.status_code == 201, r.text
    return r.json()


async def _list(client, actor, prefix, **params) -> dict:
    r = await client.get(f"/{prefix}", params=params, headers=auth(actor))
    assert r.status_code == 200, r.text
    return r.json()


# --- CRUD + guards -----------------------------------------------------------------------------


async def test_crud_happy_path(client, sup, kind) -> None:
    prefix = kind[0]
    created = await _created(
        client, sup, prefix, name="Sok Dara", location="Phnom Penh", phone="012 345 678"
    )
    assert created["is_active"] is True
    assert created["phone"] == "012345678"
    assert created["phone_display"] == "012 345 678"
    assert created["created_by"] == {
        "id": str(sup.id),
        "full_name": sup.full_name,
        "role": "supervisor",
        "telegram_username": sup.telegram_username,
        "is_system": False,
    }
    assert created["updated_by"]["id"] == str(sup.id)

    r = await client.get(f"/{prefix}/{created['id']}", headers=auth(sup))
    assert r.status_code == 200 and r.json()["name"] == "Sok Dara"

    r = await client.patch(
        f"/{prefix}/{created['id']}", json={"location": "Siem Reap"}, headers=auth(sup)
    )
    assert r.status_code == 200, r.text
    assert r.json()["location"] == "Siem Reap"
    assert r.json()["name"] == "Sok Dara"  # untouched

    r = await client.post(f"/{prefix}/{created['id']}/deactivate", headers=auth(sup))
    assert r.status_code == 200 and r.json()["is_active"] is False
    assert r.json()["deleted_at"] is not None

    r = await client.post(f"/{prefix}/{created['id']}/reactivate", headers=auth(sup))
    assert r.status_code == 200 and r.json()["is_active"] is True
    assert r.json()["deleted_at"] is None


async def test_gm_and_superadmin_can_manage(client, superadmin, make_user, kind) -> None:
    gm = await make_user(Role.GENERAL_MANAGER)
    await _created(client, gm, kind[0], name="From GM")
    await _created(client, superadmin, kind[0], name="From superadmin")


async def test_every_endpoint_requires_its_permission(client, make_user, sup, kind) -> None:
    prefix = kind[0]
    row = await _created(client, sup, prefix)
    nobody = await make_user(Role.SUPERVISOR, perms=[])
    calls = [
        client.get(f"/{prefix}", headers=auth(nobody)),
        client.get(f"/{prefix}/stats", headers=auth(nobody)),
        client.post(f"/{prefix}", json={"name": "x"}, headers=auth(nobody)),
        client.get(f"/{prefix}/{row['id']}", headers=auth(nobody)),
        client.patch(f"/{prefix}/{row['id']}", json={"name": "x"}, headers=auth(nobody)),
        client.post(f"/{prefix}/{row['id']}/deactivate", headers=auth(nobody)),
        client.post(f"/{prefix}/{row['id']}/reactivate", headers=auth(nobody)),
    ]
    for call in calls:
        assert_error(await call, 403, "MISSING_PERMISSION")


async def test_staff_with_view_only_is_read_only(client, superadmin, make_user, sup, kind) -> None:
    prefix = kind[0]
    row = await _created(client, sup, prefix)
    staff = await make_user(Role.STAFF)
    # Staff have nothing by default.
    assert_error(await client.get(f"/{prefix}", headers=auth(staff)), 403, "MISSING_PERMISSION")

    r = await client.put(f"/users/{staff.id}/permissions/{prefix}.view", headers=auth(superadmin))
    assert r.status_code == 204

    assert (await _list(client, staff, prefix))["total"] == 1
    assert (await client.get(f"/{prefix}/{row['id']}", headers=auth(staff))).status_code == 200
    assert (await client.get(f"/{prefix}/stats", headers=auth(staff))).status_code == 200
    assert_error(await _create(client, staff, prefix), 403, "MISSING_PERMISSION")
    assert_error(
        await client.patch(f"/{prefix}/{row['id']}", json={"name": "x"}, headers=auth(staff)),
        403,
        "MISSING_PERMISSION",
    )
    assert_error(
        await client.post(f"/{prefix}/{row['id']}/deactivate", headers=auth(staff)),
        403,
        "MISSING_PERMISSION",
    )
    # The other list stays closed.
    other = "customers" if prefix == "suppliers" else "suppliers"
    assert_error(await client.get(f"/{other}", headers=auth(staff)), 403, "MISSING_PERMISSION")


async def test_not_found(client, sup, kind) -> None:
    prefix, _, _, code = kind
    assert_error(await client.get(f"/{prefix}/{MISSING_ID}", headers=auth(sup)), 404, code)
    assert_error(
        await client.patch(f"/{prefix}/{MISSING_ID}", json={"name": "x"}, headers=auth(sup)),
        404,
        code,
    )
    assert_error(
        await client.post(f"/{prefix}/{MISSING_ID}/deactivate", headers=auth(sup)), 404, code
    )


async def test_deactivate_and_reactivate_are_idempotent(client, session, sup, kind) -> None:
    prefix, entity = kind[0], kind[1]
    row = await _created(client, sup, prefix)
    for _ in range(2):
        r = await client.post(f"/{prefix}/{row['id']}/deactivate", headers=auth(sup))
        assert r.status_code == 200
    for _ in range(2):
        r = await client.post(f"/{prefix}/{row['id']}/reactivate", headers=auth(sup))
        assert r.status_code == 200
    actions = list(
        await session.scalars(select(AuditLog.action).where(AuditLog.entity_type == entity))
    )
    assert sorted(actions) == sorted(
        [f"{entity}.create", f"{entity}.deactivate", f"{entity}.reactivate"]
    )


# --- Validation --------------------------------------------------------------------------------


async def test_name_rules(client, sup, kind) -> None:
    prefix = kind[0]
    assert_error(
        await client.post(f"/{prefix}", json={}, headers=auth(sup)), 422, "VALIDATION_ERROR"
    )
    assert_error(await _create(client, sup, prefix, name="   "), 422, "VALIDATION_ERROR")
    assert_error(await _create(client, sup, prefix, name="x" * 151), 422, "VALIDATION_ERROR")
    row = await _created(client, sup, prefix, name="  Sok \t  Dara  ")
    assert row["name"] == "Sok Dara"
    khmer = await _created(client, sup, prefix, name=" ហាងលក់មាន់  សុខា ")
    assert khmer["name"] == "ហាងលក់មាន់ សុខា"
    assert (await _created(client, sup, prefix, name="x" * 150))["name"] == "x" * 150
    # Name can't be cleared on update.
    assert_error(
        await client.patch(f"/{prefix}/{row['id']}", json={"name": " "}, headers=auth(sup)),
        422,
        "VALIDATION_ERROR",
    )


async def test_location_and_phone_empty_become_null(client, sup, kind) -> None:
    prefix = kind[0]
    row = await _created(client, sup, prefix, location="   ", phone="  ")
    assert row["location"] is None
    assert row["phone"] is None
    assert row["phone_display"] is None
    assert_error(await _create(client, sup, prefix, location="x" * 256), 422, "VALIDATION_ERROR")

    row = await _created(client, sup, prefix, location="  Kandal ", phone="012345678")
    assert row["location"] == "Kandal"
    r = await client.patch(
        f"/{prefix}/{row['id']}", json={"location": "", "phone": None}, headers=auth(sup)
    )
    assert r.json()["location"] is None and r.json()["phone"] is None


@pytest.mark.parametrize(
    ("raw", "stored", "display"),
    [
        ("012 345 678", "012345678", "012 345 678"),
        ("012-345-678", "012345678", "012 345 678"),
        ("(012) 345.6789", "0123456789", "012 345 6789"),
        ("+855 12-345-678", "+85512345678", "+855 12 345 678"),
        ("+855 97 777 8888", "+855977778888", "+855 97 777 8888"),
    ],
)
async def test_phone_normalization(client, sup, raw, stored, display) -> None:
    row = await _created(client, sup, "suppliers", phone=raw)
    assert row["phone"] == stored
    assert row["phone_display"] == display


@pytest.mark.parametrize(
    "raw",
    ["1234567", "+1234567", "1234567890123456", "12a45678", "++85512345678", "012 345 678 ext"],
)
async def test_invalid_phone(client, sup, kind, raw) -> None:
    assert_error(await _create(client, sup, kind[0], phone=raw), 422, "INVALID_PHONE")


async def test_invalid_phone_on_update(client, sup, kind) -> None:
    row = await _created(client, sup, kind[0])
    r = await client.patch(f"/{kind[0]}/{row['id']}", json={"phone": "123"}, headers=auth(sup))
    assert_error(r, 422, "INVALID_PHONE")


# --- Duplicate phone ---------------------------------------------------------------------------


async def test_duplicate_phone_on_create(client, sup, kind) -> None:
    prefix = kind[0]
    first = await _created(client, sup, prefix, name="A", phone="012 345 678")
    assert_error(
        await _create(client, sup, prefix, name="B", phone="012-345-678"), 409, "DUPLICATE_PHONE"
    )
    # Allowed once the other record is inactive.
    await client.post(f"/{prefix}/{first['id']}/deactivate", headers=auth(sup))
    await _created(client, sup, prefix, name="B", phone="012345678")


async def test_duplicate_phone_on_update(client, sup, kind) -> None:
    prefix = kind[0]
    await _created(client, sup, prefix, name="A", phone="012345678")
    b = await _created(client, sup, prefix, name="B", phone="098765432")
    r = await client.patch(f"/{prefix}/{b['id']}", json={"phone": "012 345 678"}, headers=auth(sup))
    assert_error(r, 409, "DUPLICATE_PHONE")
    # Re-saving its own phone is fine.
    r = await client.patch(f"/{prefix}/{b['id']}", json={"phone": "098 765 432"}, headers=auth(sup))
    assert r.status_code == 200


async def test_duplicate_phone_on_reactivate(client, sup, kind) -> None:
    prefix = kind[0]
    a = await _created(client, sup, prefix, name="A", phone="012345678")
    await client.post(f"/{prefix}/{a['id']}/deactivate", headers=auth(sup))
    await _created(client, sup, prefix, name="B", phone="012345678")
    assert_error(
        await client.post(f"/{prefix}/{a['id']}/reactivate", headers=auth(sup)),
        409,
        "DUPLICATE_PHONE",
    )


async def test_same_phone_in_both_lists_is_allowed(client, sup) -> None:
    await _created(client, sup, "suppliers", phone="012345678")
    await _created(client, sup, "customers", phone="012345678")


async def test_duplicate_phone_index_backs_up_the_check(client, sup, kind, monkeypatch) -> None:
    """Under a race the pre-check passes; the partial unique index still refuses."""
    prefix = kind[0]
    await _created(client, sup, prefix, name="A", phone="012345678")

    async def _never_taken(*args, **kwargs) -> bool:
        return False

    monkeypatch.setattr(partner_service, "_phone_taken", _never_taken)
    assert_error(
        await _create(client, sup, prefix, name="B", phone="012345678"), 409, "DUPLICATE_PHONE"
    )


# --- Search, filters, sorting, paging ----------------------------------------------------------


async def test_search(client, sup, kind) -> None:
    prefix = kind[0]
    await _created(client, sup, prefix, name="Sok Dara", location="Phnom Penh", phone="012345678")
    await _created(client, sup, prefix, name="Chan Thy", location="Siem Reap", phone="+85597777888")
    await _created(client, sup, prefix, name="100% Chicken", location="Kampot")

    async def names(q: str) -> list[str]:
        return [i["name"] for i in (await _list(client, sup, prefix, q=q))["items"]]

    assert await names("sok") == ["Sok Dara"]
    assert await names("SIEM") == ["Chan Thy"]
    assert await names("345 678") == ["Sok Dara"]
    assert await names("+855 97") == ["Chan Thy"]
    assert await names("%") == ["100% Chicken"]  # LIKE wildcards are literal
    assert await names("nothing") == []


async def test_status_filter(client, sup, kind) -> None:
    prefix = kind[0]
    await _created(client, sup, prefix, name="Active")
    gone = await _created(client, sup, prefix, name="Gone")
    await client.post(f"/{prefix}/{gone['id']}/deactivate", headers=auth(sup))

    def names(page) -> list[str]:
        return [i["name"] for i in page["items"]]

    assert names(await _list(client, sup, prefix)) == ["Active"]  # default: active
    assert names(await _list(client, sup, prefix, status="inactive")) == ["Gone"]
    assert names(await _list(client, sup, prefix, status="all")) == ["Active", "Gone"]
    assert_error(
        await client.get(f"/{prefix}", params={"status": "x"}, headers=auth(sup)),
        422,
        "VALIDATION_ERROR",
    )


async def test_sorting(client, sup, kind) -> None:
    prefix = kind[0]
    for name in ["banana", "Apple", "cherry"]:
        await _created(client, sup, prefix, name=name)

    async def names(sort: str) -> list[str]:
        return [i["name"] for i in (await _list(client, sup, prefix, sort=sort))["items"]]

    assert await names("name") == ["Apple", "banana", "cherry"]  # case-insensitive
    assert await names("-name") == ["cherry", "banana", "Apple"]
    assert await names("created_at") == ["banana", "Apple", "cherry"]
    assert await names("-created_at") == ["cherry", "Apple", "banana"]
    assert_error(
        await client.get(f"/{prefix}", params={"sort": "phone"}, headers=auth(sup)),
        422,
        "VALIDATION_ERROR",
    )


async def test_paging(client, sup, kind) -> None:
    prefix = kind[0]
    for i in range(25):
        await _created(client, sup, prefix, name=f"P{i:02d}")
    first = await _list(client, sup, prefix)
    assert first["total"] == 25 and first["page_size"] == 20 and len(first["items"]) == 20
    second = await _list(client, sup, prefix, page=2)
    assert [i["name"] for i in second["items"]] == [f"P{i:02d}" for i in range(20, 25)]
    assert len((await _list(client, sup, prefix, page_size=100))["items"]) == 25
    assert_error(
        await client.get(f"/{prefix}", params={"page_size": 101}, headers=auth(sup)),
        422,
        "VALIDATION_ERROR",
    )


# --- Stats -------------------------------------------------------------------------------------


async def test_stats(client, session, sup, kind, monkeypatch) -> None:
    prefix, _, model, _ = kind
    # 2026-09-30 18:00 UTC is already 2026-10-01 01:00 in Phnom Penh (UTC+7):
    # "this month" starts at 2026-09-30 17:00 UTC.
    now = datetime(2026, 9, 30, 18, 0, tzinfo=UTC)
    monkeypatch.setattr(partner_service, "utcnow", lambda: now)
    session.add_all(
        [
            model(name="Old active", created_at=datetime(2026, 9, 1, tzinfo=UTC)),
            model(name="Just before", created_at=datetime(2026, 9, 30, 16, 59, tzinfo=UTC)),
            model(name="Just after", created_at=datetime(2026, 9, 30, 17, 0, tzinfo=UTC)),
            model(
                name="New but inactive",
                created_at=datetime(2026, 9, 30, 17, 30, tzinfo=UTC),
                is_active=False,
            ),
            model(
                name="Old inactive", created_at=datetime(2026, 8, 1, tzinfo=UTC), is_active=False
            ),
        ]
    )
    await session.commit()

    r = await client.get(f"/{prefix}/stats", headers=auth(sup))
    assert r.status_code == 200, r.text
    assert r.json() == {"total_active": 3, "new_this_month": 2, "inactive": 2}


def test_month_start_uses_business_timezone() -> None:
    start = partner_service.month_start_utc(datetime(2026, 9, 30, 16, 59, tzinfo=UTC))
    assert start == datetime(2026, 8, 31, 17, 0, tzinfo=UTC)
    start = partner_service.month_start_utc(datetime(2026, 9, 30, 17, 0, tzinfo=UTC))
    assert start == datetime(2026, 9, 30, 17, 0, tzinfo=UTC)


# --- Audit -------------------------------------------------------------------------------------


async def test_audit_entries(client, session, superadmin, sup, kind) -> None:
    prefix, entity, _, _ = kind
    row = await _created(client, sup, prefix, name="Sok Dara", phone="012345678")
    await client.patch(
        f"/{prefix}/{row['id']}", json={"name": "Sok Dara 2", "location": "Kep"}, headers=auth(sup)
    )
    # No-op update writes nothing.
    await client.patch(f"/{prefix}/{row['id']}", json={"location": "Kep"}, headers=auth(sup))
    await client.post(f"/{prefix}/{row['id']}/deactivate", headers=auth(sup))
    await client.post(f"/{prefix}/{row['id']}/reactivate", headers=auth(sup))

    logs = list(
        await session.scalars(
            select(AuditLog).where(AuditLog.entity_type == entity).order_by(AuditLog.id)
        )
    )
    assert [log.action for log in logs] == [
        f"{entity}.create",
        f"{entity}.update",
        f"{entity}.deactivate",
        f"{entity}.reactivate",
    ]
    assert all(str(log.entity_id) == row["id"] and log.actor_id == sup.id for log in logs)
    assert logs[0].details == {"name": "Sok Dara", "location": None, "phone": "012345678"}
    assert logs[1].details == {
        "name": "Sok Dara 2",
        "changes": {"name": ["Sok Dara", "Sok Dara 2"], "location": [None, "Kep"]},
    }
    assert logs[2].details == {"name": "Sok Dara 2"}

    # Audit log API: entity filter + entity reference with the current name.
    r = await client.get(
        "/audit-logs",
        params={"entity_type": entity, "entity_id": row["id"]},
        headers=auth(superadmin),
    )
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert len(items) == 4
    assert all(
        i["entity"] == {"type": entity, "id": row["id"], "name": "Sok Dara 2"} for i in items
    )
    assert all(i["target"] is None for i in items)

    r = await client.get("/audit-logs", params={"action": "user.create"}, headers=auth(superadmin))
    assert all(i["entity"] is None for i in r.json()["items"])


async def test_audit_entity_type_filter_separates_lists(client, superadmin, sup) -> None:
    await _created(client, sup, "suppliers", name="S")
    await _created(client, sup, "customers", name="C")
    r = await client.get(
        "/audit-logs", params={"entity_type": "customer"}, headers=auth(superadmin)
    )
    assert [i["entity"]["name"] for i in r.json()["items"]] == ["C"]
