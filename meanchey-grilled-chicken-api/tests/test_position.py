"""Position is a free-text job title for staff. It never affects access."""

import pytest

from app.models import Role
from app.schemas.user import normalize_position
from tests.conftest import assert_error, auth

KHMER = "អ្នកដឹកជញ្ជូន"


def _staff(username: str, position: object = "Grill cook") -> dict:
    return {
        "role": "staff",
        "position": position,
        "full_name": "Staff",
        "telegram_username": username,
    }


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Grill cook", "Grill cook"),
        ("  Grill    cook  ", "Grill cook"),
        ("Head\tof\n  delivery", "Head of delivery"),
        (f"  {KHMER}  ", KHMER),
        ("GRILL Cook", "GRILL Cook"),  # case kept as typed
        ("   ", None),
        ("", None),
        (None, None),
    ],
)
def test_normalize_position(raw, expected) -> None:
    assert normalize_position(raw) == expected


@pytest.mark.parametrize("position", ["Grill cook", KHMER])
async def test_create_staff_with_free_text_position(client, superadmin, position) -> None:
    r = await client.post("/users", json=_staff("free_text", position), headers=auth(superadmin))
    assert r.status_code == 201, r.text
    assert r.json()["position"] == position


async def test_create_normalizes_whitespace(client, superadmin) -> None:
    r = await client.post(
        "/users", json=_staff("spaced_out", "  Grill \t  cook "), headers=auth(superadmin)
    )
    assert r.status_code == 201, r.text
    assert r.json()["position"] == "Grill cook"


@pytest.mark.parametrize("position", ["", "   ", None])
async def test_empty_position_is_required_for_staff(client, superadmin, position) -> None:
    r = await client.post("/users", json=_staff("no_pos_staff", position), headers=auth(superadmin))
    assert_error(r, 422, "POSITION_REQUIRED")


async def test_position_max_50_chars(client, superadmin) -> None:
    ok = await client.post("/users", json=_staff("fifty_ok", "x" * 50), headers=auth(superadmin))
    assert ok.status_code == 201, ok.text
    r = await client.post("/users", json=_staff("too_long", "x" * 51), headers=auth(superadmin))
    assert_error(r, 422, "VALIDATION_ERROR")
    khmer_long = await client.post(
        "/users", json=_staff("khmer_long", "ក" * 51), headers=auth(superadmin)
    )
    assert_error(khmer_long, 422, "VALIDATION_ERROR")


async def test_non_staff_cannot_have_position(client, superadmin) -> None:
    body = {
        "role": "supervisor",
        "position": "Shift lead",
        "full_name": "Sup",
        "telegram_username": "sup_with_pos",
    }
    assert_error(
        await client.post("/users", json=body, headers=auth(superadmin)),
        422,
        "POSITION_NOT_ALLOWED",
    )


async def test_update_position(client, make_user) -> None:
    gm = await make_user(Role.GENERAL_MANAGER)
    staff = await make_user(Role.STAFF, position="worker")
    r = await client.patch(f"/users/{staff.id}", json={"position": f" {KHMER} "}, headers=auth(gm))
    assert r.status_code == 200, r.text
    assert r.json()["position"] == KHMER
    r = await client.patch(f"/users/{staff.id}", json={"position": "  "}, headers=auth(gm))
    assert_error(r, 422, "POSITION_REQUIRED")


async def test_filter_is_case_insensitive_exact_match(client, make_user) -> None:
    gm = await make_user(Role.GENERAL_MANAGER)
    await make_user(Role.STAFF, "cook_one", position="Grill cook")
    await make_user(Role.STAFF, "cook_two", position="grill COOK")
    await make_user(Role.STAFF, "cook_head", position="Head grill cook")
    r = await client.get("/users", params={"position": "GRILL cook"}, headers=auth(gm))
    assert {u["telegram_username"] for u in r.json()["items"]} == {"cook_one", "cook_two"}


async def test_q_searches_position(client, make_user) -> None:
    gm = await make_user(Role.GENERAL_MANAGER)
    await make_user(Role.STAFF, "khmer_driver", position=KHMER)
    await make_user(Role.STAFF, "the_cook", position="Grill cook")
    r = await client.get("/users", params={"q": "grill"}, headers=auth(gm))
    assert [u["telegram_username"] for u in r.json()["items"]] == ["the_cook"]
    r = await client.get("/users", params={"q": "ដឹក"}, headers=auth(gm))
    assert [u["telegram_username"] for u in r.json()["items"]] == ["khmer_driver"]


async def test_positions_endpoint_distinct_sorted_active_only(client, make_user) -> None:
    gm = await make_user(Role.GENERAL_MANAGER)
    await make_user(Role.STAFF, position="Grill cook")
    await make_user(Role.STAFF, position="Grill cook")
    await make_user(Role.STAFF, position="grill cook")  # same group, less used spelling
    await make_user(Role.STAFF, position="driver")
    await make_user(Role.STAFF, position=KHMER)
    await make_user(Role.STAFF, position="Cashier", is_active=False)

    r = await client.get("/users/positions", headers=auth(gm))
    assert r.status_code == 200, r.text
    assert r.json() == ["driver", "Grill cook", KHMER]


async def test_positions_endpoint_requires_view_and_scope(client, superadmin, make_user) -> None:
    staff = await make_user(Role.STAFF, position="Grill cook")
    assert_error(
        await client.get("/users/positions", headers=auth(staff)), 403, "MISSING_PERMISSION"
    )
    # A supervisor with users.view sees staff positions (staff are in their scope).
    sup = await make_user(Role.SUPERVISOR)
    assert (await client.get("/users/positions", headers=auth(sup))).json() == ["Grill cook"]
    assert (await client.get("/users/positions", headers=auth(superadmin))).json() == ["Grill cook"]


async def test_position_has_no_effect_on_access(client, make_user) -> None:
    """Two staff with the same grants but different positions get identical access."""
    a = await make_user(Role.STAFF, "staff_driver", position=KHMER)
    b = await make_user(Role.STAFF, "staff_cook", position="Grill cook")
    me_a = (await client.get("/auth/me", headers=auth(a))).json()
    me_b = (await client.get("/auth/me", headers=auth(b))).json()
    for key in ("permissions", "manageable_roles", "can_self_reset_password"):
        assert me_a[key] == me_b[key]
    for path in ("/users", "/users/positions", "/audit-logs"):
        ra = await client.get(path, headers=auth(a))
        rb = await client.get(path, headers=auth(b))
        assert (ra.status_code, ra.json()["error"]["code"]) == (
            rb.status_code,
            rb.json()["error"]["code"],
        )
