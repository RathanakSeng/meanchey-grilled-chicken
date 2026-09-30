"""Packaging plan between steps 2 and 3: feature and permissions, lifecycle, rules, step 3 gate and
comment rule, list and detail, audit."""

import pytest
from sqlalchemy import delete, select

from app.bootstrap import bootstrap
from app.models import AuditLog, Permission, ProductionPlan, Role, UserPermission
from app.permissions import registry
from tests.conftest import assert_error, auth
from tests.test_production import PRODUCED, Api, Clock, ok, standardize_body

PLAN_FEATURE = registry.FEATURES_BY_CODE["production_plan"]
PLAN_CODES = {"production_plan.view", "production_plan.manage"}


@pytest.fixture
async def gm(make_user):
    return await make_user(Role.GENERAL_MANAGER)


@pytest.fixture
def api(client, gm) -> Api:
    return Api(client, gm)


@pytest.fixture
async def supplier(client, gm) -> dict:
    return ok(await client.post("/suppliers", json={"name": "Sokha Farm"}, headers=auth(gm)), 201)


class Plans:
    def __init__(self, client, actor) -> None:
        self.client, self.headers = client, auth(actor)

    def list(self, **params):
        return self.client.get("/production-plans", params=params, headers=self.headers)

    def get(self, batch: dict):
        return self.client.get(f"/production-plans/{batch['id']}", headers=self.headers)

    def patch(self, batch: dict, version: int | None = None, **fields):
        body = {"version": batch["version"] if version is None else version, **fields}
        return self.client.patch(
            f"/production-plans/{batch['id']}", json=body, headers=self.headers
        )

    def confirm(self, batch: dict, version: int | None = None):
        body = {"version": batch["version"] if version is None else version}
        return self.client.post(
            f"/production-plans/{batch['id']}/confirm", json=body, headers=self.headers
        )


@pytest.fixture
def clock(monkeypatch) -> Clock:
    return Clock(monkeypatch)


@pytest.fixture
def plans(client, gm) -> Plans:
    return Plans(client, gm)


def _as_batch(detail: dict) -> dict:
    """A plan detail carries the batch id and version under other names."""
    return {"id": detail["batch_id"], "version": detail["version"]}


async def _set_level(client, actor, target, level: str) -> None:
    r = await client.put(
        f"/users/{target.id}/features/production_plan", json={"level": level}, headers=auth(actor)
    )
    assert r.status_code == 200, r.text


# --- Feature and permissions ---------------------------------------------------------------------


def test_plan_feature_levels() -> None:
    assert PLAN_FEATURE.menu == "workstation"
    assert PLAN_FEATURE.applies_to == (Role.GENERAL_MANAGER, Role.SUPERVISOR)
    assert PLAN_FEATURE.level_map == {
        "off": frozenset(),
        "view": {"production_plan.view"},
        "full": PLAN_CODES,
    }
    assert registry.DEFAULT_PERMISSIONS[Role.GENERAL_MANAGER] >= PLAN_CODES
    assert not PLAN_CODES & registry.DEFAULT_PERMISSIONS[Role.SUPERVISOR]
    assert not PLAN_CODES & registry.DEFAULT_PERMISSIONS[Role.STAFF]


async def test_plan_feature_is_not_for_staff(client, gm, make_user) -> None:
    staff = await make_user(Role.STAFF)
    r = await client.put(
        f"/users/{staff.id}/features/production_plan", json={"level": "view"}, headers=auth(gm)
    )
    assert_error(r, 422, "FEATURE_NOT_APPLICABLE")


async def test_supervisor_levels(client, gm, make_user, api, supplier, plans) -> None:
    sup = await make_user(Role.SUPERVISOR)
    sup_plans = Plans(client, sup)
    batch = await api.step2(supplier, plan=False)
    # Off by default.
    assert_error(await sup_plans.list(), 403, "MISSING_PERMISSION")
    assert_error(await sup_plans.get(batch), 403, "MISSING_PERMISSION")
    # View only: reads, can't set.
    await _set_level(client, gm, sup, "view")
    assert ok(await sup_plans.list())["total"] == 1
    assert ok(await sup_plans.get(batch))["plan"]["status"] == "pending"
    assert_error(await sup_plans.patch(batch, expected_big=1), 403, "MISSING_PERMISSION")
    assert_error(await sup_plans.confirm(batch), 403, "MISSING_PERMISSION")
    # Full access: sets and confirms.
    await _set_level(client, gm, sup, "full")
    detail = ok(await sup_plans.patch(batch, expected_big=7, expected_small=5))
    assert ok(await sup_plans.confirm(_as_batch(detail)))["plan"]["status"] == "confirmed"


async def test_backfill_gives_the_plan_to_existing_gms_only(session, make_user) -> None:
    gm = await make_user(Role.GENERAL_MANAGER)
    sup = await make_user(Role.SUPERVISOR)
    # As before this feature was deployed.
    await session.execute(
        delete(UserPermission).where(UserPermission.permission_code.in_(PLAN_CODES))
    )
    await session.execute(delete(Permission).where(Permission.code.in_(PLAN_CODES)))
    await session.execute(delete(AuditLog))
    await session.commit()

    await bootstrap(session)

    async def held(user) -> set[str]:
        return set(
            await session.scalars(
                select(UserPermission.permission_code).where(
                    UserPermission.user_id == user.id,
                    UserPermission.permission_code.in_(PLAN_CODES),
                )
            )
        )

    assert await held(gm) == PLAN_CODES
    assert await held(sup) == set()


# --- Lifecycle -----------------------------------------------------------------------------------


async def test_step_2_finish_creates_a_pending_plan(api, supplier) -> None:
    batch = await api.step1(supplier)
    assert batch["plan"] is None and batch["plan_legacy"] is False
    batch = ok(await api.patch(batch, "produced", **PRODUCED))
    batch = ok(await api.finish(batch, "produced"))
    assert batch["plan"] == {
        **batch["plan"],
        "status": "pending",
        "expected_big": None,
        "expected_small": None,
        "note": None,
        "confirmed_by": None,
        "confirmed_at": None,
    }
    assert batch["plan_legacy"] is False
    assert batch["standardize"]["status"] == "draft"  # the row exists, but it's locked


async def test_step_3_is_locked_until_the_plan_is_confirmed(api, gm, supplier, plans) -> None:
    batch = await api.step2(supplier, plan=False)
    assert_error(
        await api.patch(batch, "standardize", big_packages=1), 409, "PRODUCTION_PLAN_REQUIRED"
    )
    assert_error(await api.finish(batch, "standardize"), 409, "PRODUCTION_PLAN_REQUIRED")
    # Saving doesn't unlock it; confirming does.
    detail = ok(await plans.patch(batch, expected_big=7, expected_small=5))
    batch = {**batch, "version": detail["version"]}
    assert_error(
        await api.patch(batch, "standardize", big_packages=1), 409, "PRODUCTION_PLAN_REQUIRED"
    )
    detail = ok(await plans.confirm(batch))
    assert detail["plan"]["status"] == "confirmed"
    assert detail["plan"]["confirmed_by"]["id"] == str(gm.id)
    batch = {**batch, "version": detail["version"]}
    batch = ok(await api.patch(batch, "standardize", **standardize_body()))
    assert ok(await api.finish(batch, "standardize"))["status"] == "completed"


async def test_confirm_requires_both_values(api, supplier, plans) -> None:
    batch = await api.step2(supplier, plan=False)
    r = await plans.confirm(batch)
    assert_error(r, 422, "VALIDATION_ERROR")
    locs = [f["loc"] for f in r.json()["error"]["details"]["fields"]]
    assert locs == [["plan", "expected_big"], ["plan", "expected_small"]]
    detail = ok(await plans.patch(batch, expected_big=3))
    r = await plans.confirm(_as_batch(detail))
    assert [f["loc"] for f in r.json()["error"]["details"]["fields"]] == [
        ["plan", "expected_small"]
    ]


async def test_plan_cannot_exceed_the_produced_pieces(api, supplier, plans) -> None:
    batch = await api.step2(supplier, plan=False)  # 10 chickens: 20 wings, 20 thighs
    r = await plans.patch(batch, expected_big=8, expected_small=5)  # 2×8 + 5 = 21
    assert_error(r, 422, "PRODUCTION_PLAN_EXCEEDS_OUTPUT")
    assert r.json()["error"]["details"] == {
        "wings": {"available": 20, "planned": 21},
        "thighs": {"available": 20, "planned": 21},
    }
    # One value alone isn't checked yet; exactly all pieces is fine.
    detail = ok(await plans.patch(batch, expected_big=10))
    detail = ok(await plans.patch(_as_batch(detail), expected_small=0))
    assert (detail["plan"]["expected_big"], detail["plan"]["expected_small"]) == (10, 0)


async def test_confirm_rechecks_the_output(api, supplier, plans) -> None:
    """Fewer chickens after a reopen: the kept plan no longer fits and can't be confirmed."""
    batch = await api.step2(supplier)  # plan 7 + 5 confirmed (19 pieces of 20)
    batch = ok(await api.reopen(batch, "raw-material"))
    batch = ok(await api.patch(batch, "raw-material", quantity=5))
    batch = ok(await api.finish(batch, "raw-material"))
    batch = ok(await api.finish(batch, "produced"))
    assert batch["plan"]["status"] == "pending"
    assert_error(await plans.confirm(batch), 422, "PRODUCTION_PLAN_EXCEEDS_OUTPUT")
    detail = ok(await plans.patch(batch, expected_big=2, expected_small=6))
    assert ok(await plans.confirm(_as_batch(detail)))["plan"]["status"] == "confirmed"


async def test_confirmed_plan_stays_confirmed_when_edited(api, supplier, plans) -> None:
    batch = await api.step2(supplier)
    confirmed_at = batch["plan"]["confirmed_at"]
    detail = ok(await plans.patch(batch, expected_small=3, note="  Two boxes short  "))
    assert detail["plan"]["status"] == "confirmed"
    assert detail["plan"]["confirmed_at"] == confirmed_at
    assert detail["plan"]["note"] == "Two boxes short"
    assert detail["plan"]["updated_at"] >= confirmed_at
    # A confirmed plan can't lose a value.
    r = await plans.patch(_as_batch(detail), expected_big=None)
    assert_error(r, 422, "VALIDATION_ERROR")


async def test_plan_is_locked_once_step_3_is_finished(api, supplier, plans) -> None:
    batch = await api.completed(supplier)
    assert_error(await plans.patch(batch, expected_big=1), 409, "PRODUCTION_PLAN_LOCKED")
    assert_error(await plans.confirm(batch), 409, "PRODUCTION_PLAN_LOCKED")
    assert ok(await plans.get(batch))["editable"] is False


async def test_reopen_step_3_keeps_the_plan_confirmed_and_editable(api, supplier, plans) -> None:
    batch = await api.completed(supplier)
    batch = ok(await api.reopen(batch, "standardize"))
    assert batch["plan"]["status"] == "confirmed"
    detail = ok(await plans.get(batch))
    assert detail["editable"] is True
    detail = ok(await plans.patch(batch, expected_big=6, expected_small=7))
    assert detail["plan"]["status"] == "confirmed"


@pytest.mark.parametrize("step", ["raw-material", "produced"])
async def test_reopen_step_1_or_2_puts_the_plan_back_to_pending(api, supplier, plans, step) -> None:
    batch = await api.completed(supplier)
    batch = ok(await api.reopen(batch, step))
    assert batch["plan"]["status"] == "pending"
    assert (batch["plan"]["expected_big"], batch["plan"]["expected_small"]) == (7, 5)
    assert batch["plan"]["confirmed_by"] is None
    # Step 2 is a draft again: nothing to plan against yet.
    assert_error(await plans.patch(batch, expected_big=1), 409, "PRODUCTION_STEP_NOT_READY")
    assert_error(await plans.confirm(batch), 409, "PRODUCTION_STEP_NOT_READY")
    if step == "raw-material":
        batch = ok(await api.finish(batch, "raw-material"))
    batch = ok(await api.finish(batch, "produced"))
    assert batch["plan"]["status"] == "pending"
    assert_error(await api.finish(batch, "standardize"), 409, "PRODUCTION_PLAN_REQUIRED")
    detail = ok(await plans.confirm(batch))
    batch = {**batch, "version": detail["version"]}
    assert ok(await api.finish(batch, "standardize"))["status"] == "completed"


async def test_plan_writes_use_the_batch_version(api, supplier, plans) -> None:
    batch = await api.step2(supplier, plan=False)
    detail = ok(await plans.patch(batch, expected_big=1))
    assert detail["version"] == batch["version"] + 1
    r = await plans.patch(batch, expected_big=2)  # stale
    assert_error(r, 409, "PRODUCTION_CONFLICT")
    assert r.json()["error"]["details"]["batch"]["plan"]["expected_big"] == 1
    assert_error(await plans.confirm(batch), 409, "PRODUCTION_CONFLICT")
    # A plan write also changes the batch version: a stale step 3 save conflicts.
    detail = ok(await plans.patch(_as_batch(detail), expected_small=1))
    detail = ok(await plans.confirm(_as_batch(detail)))
    stale = {**batch, "version": detail["version"] - 1}
    assert_error(await api.patch(stale, "standardize", big_packages=1), 409, "PRODUCTION_CONFLICT")


async def test_cancelled_batch_plan_is_read_only(client, gm, api, supplier, plans) -> None:
    batch = await api.step2(supplier, plan=False)
    batch = ok(await api.cancel(batch))
    assert_error(await plans.patch(batch, expected_big=1), 409, "PRODUCTION_CANCELLED")
    assert_error(await plans.confirm(batch), 409, "PRODUCTION_CANCELLED")
    detail = ok(await plans.get(batch))
    assert (detail["batch_status"], detail["editable"]) == ("cancelled", False)
    # Cancelled batches never appear in the plan list.
    assert ok(await plans.list(status="all"))["total"] == 0


async def test_plan_audit_entries(api, session, supplier, plans) -> None:
    batch = await api.step2(supplier, plan=False)
    detail = ok(await plans.patch(batch, expected_big=7, expected_small=5, note="ok"))
    detail = ok(await plans.patch(_as_batch(detail), expected_big=7))  # no change: no entry
    ok(await plans.confirm(_as_batch(detail)))
    logs = list(
        await session.scalars(
            select(AuditLog).where(AuditLog.action.like("production_plan.%")).order_by(AuditLog.id)
        )
    )
    assert [(log.action, log.entity_type, str(log.entity_id)) for log in logs] == [
        ("production_plan.update", "production_batch", batch["id"]),
        ("production_plan.confirm", "production_batch", batch["id"]),
    ]
    assert logs[0].details == {
        "code": batch["code"],
        "changes": {"expected_big": [None, 7], "expected_small": [None, 5], "note": [None, "ok"]},
    }
    assert logs[1].details == {"code": batch["code"], "expected_big": 7, "expected_small": 5}


async def test_legacy_batch_without_a_plan(api, session, supplier, plans) -> None:
    """Completed before plans existed: no plan, marked legacy; reopening creates one."""
    batch = await api.completed(supplier, big=6, small=7, comment="Packed before plans")
    await session.execute(delete(ProductionPlan))
    await session.commit()
    batch = await api.get(batch)
    assert (batch["plan"], batch["plan_legacy"]) == (None, True)
    assert batch["standardize"]["plan_matches"] is None
    detail = ok(await plans.get(batch))
    assert (detail["plan"], detail["plan_legacy"], detail["editable"]) == (None, True, False)
    assert_error(await plans.patch(batch, expected_big=1), 409, "PRODUCTION_PLAN_LOCKED")

    batch = ok(await api.reopen(batch, "standardize"))
    assert batch["plan_legacy"] is False
    plan = batch["plan"]
    assert (plan["status"], plan["expected_big"], plan["expected_small"]) == ("pending", 6, 7)
    assert_error(await api.finish(batch, "standardize"), 409, "PRODUCTION_PLAN_REQUIRED")
    detail = ok(await plans.confirm(batch))
    batch = {**batch, "version": detail["version"]}
    assert ok(await api.finish(batch, "standardize"))["status"] == "completed"


# --- Step 3 against the plan ---------------------------------------------------------------------


@pytest.mark.parametrize(("big", "small"), [(6, 7), (7, 3)])
async def test_packs_that_differ_from_the_plan_need_a_comment(api, supplier, big, small) -> None:
    batch = await api.step2(supplier)  # plan 7 + 5
    rejected = 20 - 2 * big - small
    body = standardize_body(big=big, small=small, rejected_wings=rejected, rejected_thighs=rejected)
    batch = ok(await api.patch(batch, "standardize", **body))
    assert batch["standardize"]["plan_matches"] is False
    r = await api.finish(batch, "standardize")
    assert_error(r, 422, "PRODUCTION_PLAN_COMMENT_REQUIRED")
    assert r.json()["error"]["details"] == {
        "planned": {"big": 7, "small": 5},
        "actual": {"big": big, "small": small},
    }
    batch = ok(await api.patch(batch, "standardize", comment="   "))
    assert_error(await api.finish(batch, "standardize"), 422, "PRODUCTION_PLAN_COMMENT_REQUIRED")
    batch = ok(await api.patch(batch, "standardize", comment="Two thighs dropped"))
    assert ok(await api.finish(batch, "standardize"))["status"] == "completed"


async def test_matching_packs_need_no_comment(api, supplier) -> None:
    batch = await api.step2(supplier)
    assert batch["standardize"]["plan_matches"] is None  # no actual values yet
    batch = ok(await api.patch(batch, "standardize", big_packages=7))
    assert batch["standardize"]["plan_matches"] is None
    batch = ok(await api.patch(batch, "standardize", **standardize_body()))
    assert batch["standardize"]["plan_matches"] is True
    batch = ok(await api.finish(batch, "standardize"))
    assert (batch["status"], batch["standardize"]["comment"]) == ("completed", None)


async def test_balance_is_checked_before_the_comment(api, supplier) -> None:
    batch = await api.step2(supplier)
    batch = ok(await api.patch(batch, "standardize", **standardize_body(big=6)))
    assert_error(await api.finish(batch, "standardize"), 422, "PRODUCTION_BALANCE_MISMATCH")


# --- Lists and detail ----------------------------------------------------------------------------


async def test_waiting_for_plan_filter(client, gm, api, supplier) -> None:
    pending = await api.step2(supplier, plan=False)
    confirmed = await api.step2(supplier)
    await api.step1(supplier)  # waiting for step 2

    async def codes(**params) -> list[str]:
        r = await client.get("/production", params=params, headers=auth(gm))
        return [item["code"] for item in ok(r)["items"]]

    assert await codes(waiting_step="plan") == [pending["code"]]
    assert await codes(waiting_step="3") == [confirmed["code"]]
    assert_error(
        await client.get("/production?waiting_step=4", headers=auth(gm)), 422, "VALIDATION_ERROR"
    )


async def test_plan_list(api, supplier, plans, clock) -> None:
    clock.day("2026-09-01")
    pending = await api.step2(supplier, plan=False)
    clock.day("2026-09-02")
    confirmed = await api.step2(supplier, quantity=12)
    clock.day("2026-09-03")
    completed = await api.completed(supplier)
    cancelled = await api.step2(supplier, plan=False)
    ok(await api.cancel(cancelled))
    await api.step1(supplier)  # no plan yet

    async def listed(**params) -> tuple[list[str], int]:
        page = ok(await plans.list(**params))
        return [i["code"] for i in page["items"]], page["pending_count"]

    assert await listed() == ([pending["code"]], 1)  # pending by default
    assert await listed(status="confirmed") == ([confirmed["code"]], 1)
    assert await listed(status="completed") == ([completed["code"]], 1)
    assert await listed(status="all") == (
        [completed["code"], confirmed["code"], pending["code"]],  # latest production date first
        1,
    )
    assert await listed(status="all", q=confirmed["code"]) == ([confirmed["code"]], 1)
    assert await listed(status="all", q="sokha") == (
        [completed["code"], confirmed["code"], pending["code"]],
        1,
    )

    item = ok(await plans.list(status="confirmed"))["items"][0]
    assert item == {
        **item,
        "batch_id": confirmed["id"],
        "batch_status": "in_progress",
        "production_date": "2026-09-02",
        "quantity": 12,
        "wings_count": 24,
        "thighs_count": 24,
        "status": "confirmed",
        "expected_big": 7,
        "expected_small": 5,
    }
    assert item["supplier"]["name"] == "Sokha Farm"


async def test_plan_detail(api, supplier, plans) -> None:
    batch = await api.step2(supplier, plan=False)
    detail = ok(await plans.get(batch))
    assert detail["code"] == batch["code"]
    assert (detail["version"], detail["editable"], detail["plan_legacy"]) == (
        batch["version"],
        True,
        False,
    )
    produced = detail["produced"]
    assert (produced["wings_kg"], produced["thighs_kg"], produced["marinade_g"]) == (
        "4.200",
        "6.800",
        "350.0",
    )
    assert (produced["wings_count"], produced["thighs_count"]) == (20, 20)
    assert [(b["item_code"], b["name_km"], b["produced_kg"]) for b in produced["byproducts"]] == [
        ("gizzard", "កោះមាន់", "0.500"),
        ("liver", "ថ្លើមមាន់", "0.500"),
        ("heart", "បេះដូងមាន់", "0.500"),
        ("head", "ក្បាលមាន់", "0.500"),
    ]
    assert detail["standardize"]["big_packages"] is None
    assert detail["supplier"]["name"] == "Sokha Farm"

    # Before step 2 is finished there's no plan, and it isn't legacy either.
    early = await api.step1(supplier)
    detail = ok(await plans.get(early))
    assert (detail["plan"], detail["plan_legacy"], detail["editable"]) == (None, False, False)
    assert_error(await plans.patch(early, expected_big=1), 409, "PRODUCTION_STEP_NOT_READY")
    missing = {"id": "00000000-0000-0000-0000-000000000000", "version": 1}
    assert_error(await plans.get(missing), 404, "PRODUCTION_NOT_FOUND")
