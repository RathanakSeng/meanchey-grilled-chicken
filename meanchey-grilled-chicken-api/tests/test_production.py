"""Production batches: steps, drafts and versions, finish / reopen / cancel, step dates, codes,
stats, list."""

import asyncio
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
from httpx import Response
from sqlalchemy import select

from app.models import AuditLog, Role
from app.services import production_service
from tests.conftest import assert_error, auth

BYPRODUCTS = ["gizzard", "liver", "heart", "head"]
STEP_KEYS = ("raw_material", "produced", "standardize")
DATE_KEYS = {
    "raw_material": "import_date",
    "produced": "production_date",
    "standardize": "packaging_date",
}
PHNOM_PENH = ZoneInfo("Asia/Phnom_Penh")
PRODUCED = {
    "wings_kg": "4.2",
    "thighs_kg": "6.8",
    "marinade_g": "350",
    "byproducts": {code: "0.5" for code in BYPRODUCTS},
}


def standardize_body(big=7, small=5, rejected_wings=1, rejected_thighs=1, **extra) -> dict:
    """Defaults balance a 10-chicken batch: 2×7 + 5 + 1 = 20 wings and 20 thighs."""
    return {
        "big_packages": big,
        "small_packages": small,
        "rejected_wings": rejected_wings,
        "rejected_thighs": rejected_thighs,
        "byproducts": {c: {"carry_kg": "0.4", "rejected_kg": "0.1"} for c in BYPRODUCTS},
        **extra,
    }


def ok(r: Response, status: int = 200) -> dict:
    assert r.status_code == status, r.text
    return r.json()


class Api:
    def __init__(self, client, actor) -> None:
        self.client, self.headers = client, auth(actor)

    async def create(self, **body) -> dict:
        return ok(await self.client.post("/production", json=body, headers=self.headers), 201)

    async def get(self, batch: dict) -> dict:
        return ok(await self.client.get(f"/production/{batch['id']}", headers=self.headers))

    def patch(self, batch: dict, step: str, version: int | None = None, **fields):
        body = {"version": batch["version"] if version is None else version, **fields}
        return self.client.patch(
            f"/production/{batch['id']}/{step}", json=body, headers=self.headers
        )

    def finish(self, batch: dict, step: str):
        return self.client.post(
            f"/production/{batch['id']}/{step}/finish",
            json={"version": batch["version"]},
            headers=self.headers,
        )

    def reopen(self, batch: dict, step: str):
        return self.client.post(
            f"/production/{batch['id']}/{step}/reopen",
            json={"version": batch["version"]},
            headers=self.headers,
        )

    def cancel(self, batch: dict, reason: str = "Wrong delivery"):
        return self.client.post(
            f"/production/{batch['id']}/cancel",
            json={"version": batch["version"], "reason": reason},
            headers=self.headers,
        )

    async def step1(self, supplier: dict, quantity: int = 10, **extra) -> dict:
        batch = await self.create(
            supplier_id=supplier["id"], weight_kg="25.500", quantity=quantity, **extra
        )
        return ok(await self.finish(batch, "raw-material"))

    async def step2(self, supplier: dict, quantity: int = 10, **extra) -> dict:
        batch = await self.step1(supplier, quantity, **extra)
        batch = ok(await self.patch(batch, "produced", **PRODUCED))
        return ok(await self.finish(batch, "produced"))

    async def completed(self, supplier: dict, **standardize) -> dict:
        batch = await self.step2(supplier)
        batch = ok(await self.patch(batch, "standardize", **standardize_body(**standardize)))
        return ok(await self.finish(batch, "standardize"))


class Clock:
    """Sets the service's "now" (creation, finish, stats). `day()` = noon that day in Phnom Penh."""

    def __init__(self, monkeypatch) -> None:
        self.now: datetime | None = None
        monkeypatch.setattr(production_service, "utcnow", lambda: self.now or datetime.now(UTC))

    def at(self, moment: datetime | None) -> None:
        self.now = moment

    def day(self, iso: str) -> None:
        self.now = datetime.combine(date.fromisoformat(iso), time(12), tzinfo=PHNOM_PENH)


@pytest.fixture
def clock(monkeypatch) -> Clock:
    return Clock(monkeypatch)


def step_dates(batch: dict) -> list[str | None]:
    return [batch[k][DATE_KEYS[k]] if batch[k] is not None else None for k in STEP_KEYS]


@pytest.fixture
async def gm(make_user):
    return await make_user(Role.GENERAL_MANAGER)


@pytest.fixture
def api(client, gm) -> Api:
    return Api(client, gm)


@pytest.fixture
async def supplier(client, gm) -> dict:
    return ok(await client.post("/suppliers", json={"name": "Sokha Farm"}, headers=auth(gm)), 201)


def _field_locs(r: Response) -> list[list[str]]:
    return [f["loc"] for f in r.json()["error"]["details"]["fields"]]


# --- Create and codes ----------------------------------------------------------------------------


async def test_create_starts_a_draft_step_1(api, session) -> None:
    batch = await api.create()
    today = production_service.business_today()
    assert batch["code"] == f"PR-{today:%Y%m%d}-001"
    assert "production_date" not in batch
    assert batch["created_at"]
    assert (batch["status"], batch["current_step"], batch["version"]) == ("in_progress", 1, 1)
    raw = batch["raw_material"]
    assert raw["status"] == "draft"
    assert raw["material_kind"] == "chicken"
    assert raw["supplier"] is None and raw["weight_kg"] is None and raw["quantity"] is None
    assert raw["import_date"] is None  # a draft has no date
    assert batch["produced"] is None and batch["standardize"] is None
    assert batch["byproducts"] == []
    assert [b["code"] for b in batch["catalog"]["byproducts"]] == BYPRODUCTS
    assert batch["catalog"]["byproducts"][0]["name_km"] == "កោះមាន់"
    assert batch["catalog"]["material_kinds"][0]["wings_per_unit"] == 2
    assert batch["created_by"]["full_name"] == "Test general_manager"

    log = await session.scalar(select(AuditLog).where(AuditLog.action == "production.create"))
    assert log.entity_type == "production_batch"
    assert str(log.entity_id) == batch["id"]
    assert log.details == {"code": batch["code"]}


async def test_create_with_initial_values(api, supplier, clock) -> None:
    clock.day("2026-05-04")
    batch = await api.create(supplier_id=supplier["id"], weight_kg=12.25, quantity=6)
    assert batch["code"] == "PR-20260504-001"
    raw = batch["raw_material"]
    assert raw["supplier"] == {
        "id": supplier["id"],
        "name": "Sokha Farm",
        "phone_display": None,
        "is_active": True,
    }
    # Weights are fixed-precision strings.
    assert raw["weight_kg"] == "12.250"
    assert raw["quantity"] == 6


async def test_codes_are_sequential_per_creation_day(api, clock) -> None:
    clock.day("2026-03-01")
    codes = [(await api.create())["code"] for _ in range(3)]
    assert codes == ["PR-20260301-001", "PR-20260301-002", "PR-20260301-003"]
    clock.day("2026-03-02")
    assert (await api.create())["code"] == "PR-20260302-001"


async def test_codes_are_unique_under_concurrent_creation(api, clock) -> None:
    clock.day("2026-03-05")
    batches = await asyncio.gather(*(api.create() for _ in range(8)))
    codes = sorted(b["code"] for b in batches)
    assert codes == [f"PR-20260305-{n:03d}" for n in range(1, 9)]


async def test_code_day_follows_business_timezone(api, clock) -> None:
    # 17:30 UTC on 30 Sep is 00:30 on 1 Oct in Phnom Penh (UTC+7).
    clock.at(datetime(2026, 9, 30, 17, 30, tzinfo=UTC))
    batch = await api.create()
    assert batch["code"] == "PR-20261001-001"
    assert batch["created_at"].startswith("2026-09-30T17:30")


async def test_the_code_never_changes(api, supplier, clock) -> None:
    clock.day("2026-03-01")
    batch = await api.create(supplier_id=supplier["id"], weight_kg="5", quantity=2)
    clock.day("2026-03-04")  # finished (and dated) days later
    batch = ok(await api.finish(batch, "raw-material"))
    batch = ok(await api.reopen(batch, "raw-material"))
    assert batch["code"] == "PR-20260301-001"


async def test_create_rejects_unknown_supplier_and_kind(api) -> None:
    r = await api.client.post(
        "/production",
        json={"supplier_id": "00000000-0000-0000-0000-000000000001"},
        headers=api.headers,
    )
    assert_error(r, 422, "SUPPLIER_NOT_FOUND")
    r = await api.client.post("/production", json={"material_kind": "duck"}, headers=api.headers)
    assert_error(r, 422, "VALIDATION_ERROR")


# --- Drafts and versions -------------------------------------------------------------------------


async def test_draft_save_is_partial_and_bumps_version(api, supplier) -> None:
    batch = await api.create()
    batch = ok(await api.patch(batch, "raw-material", weight_kg="10.5"))
    assert batch["version"] == 2
    batch = ok(await api.patch(batch, "raw-material", supplier_id=supplier["id"]))
    assert batch["version"] == 3
    assert batch["raw_material"]["weight_kg"] == "10.500"  # untouched by the second save
    batch = ok(await api.patch(batch, "raw-material", weight_kg=None))
    assert batch["raw_material"]["weight_kg"] is None
    assert batch["raw_material"]["updated_by"]["full_name"] == "Test general_manager"


@pytest.mark.parametrize(
    "fields",
    [
        {"weight_kg": "-1"},
        {"weight_kg": "1.2345"},  # more than 3 decimals
        {"weight_kg": "abc"},
        {"quantity": -1},
        {"quantity": 1.5},
    ],
)
async def test_draft_relaxed_validation(api, fields) -> None:
    batch = await api.create()
    assert_error(await api.patch(batch, "raw-material", **fields), 422, "VALIDATION_ERROR")


async def test_draft_allows_zero(api) -> None:
    batch = await api.create()
    batch = ok(await api.patch(batch, "raw-material", weight_kg="0", quantity=0))
    assert (batch["raw_material"]["weight_kg"], batch["raw_material"]["quantity"]) == ("0.000", 0)


async def test_version_is_required(api) -> None:
    batch = await api.create()
    r = await api.client.patch(
        f"/production/{batch['id']}/raw-material", json={"quantity": 3}, headers=api.headers
    )
    assert_error(r, 422, "VALIDATION_ERROR")


async def test_stale_version_is_a_conflict_with_the_current_batch(api) -> None:
    batch = await api.create()
    current = ok(await api.patch(batch, "raw-material", quantity=5))
    r = await api.patch(batch, "raw-material", quantity=7)  # still version 1
    assert_error(r, 409, "PRODUCTION_CONFLICT")
    details = r.json()["error"]["details"]["batch"]
    assert details["version"] == current["version"] == 2
    assert details["raw_material"]["quantity"] == 5
    # Finish with a stale version conflicts too.
    r = await api.finish(batch, "raw-material")
    assert_error(r, 409, "PRODUCTION_CONFLICT")


async def test_unknown_batch(api) -> None:
    r = await api.client.get(
        "/production/00000000-0000-0000-0000-000000000001", headers=api.headers
    )
    assert_error(r, 404, "PRODUCTION_NOT_FOUND")


# --- Step order and finished steps ---------------------------------------------------------------


async def test_later_steps_wait_for_the_previous_one(api, supplier) -> None:
    batch = await api.create()
    assert_error(await api.patch(batch, "produced", wings_kg="1"), 409, "PRODUCTION_STEP_NOT_READY")
    assert_error(await api.finish(batch, "produced"), 409, "PRODUCTION_STEP_NOT_READY")
    assert_error(await api.patch(batch, "standardize"), 409, "PRODUCTION_STEP_NOT_READY")
    assert_error(await api.finish(batch, "standardize"), 409, "PRODUCTION_STEP_NOT_READY")

    batch = await api.step1(supplier)
    assert_error(await api.patch(batch, "standardize"), 409, "PRODUCTION_STEP_NOT_READY")
    assert_error(await api.finish(batch, "standardize"), 409, "PRODUCTION_STEP_NOT_READY")


async def test_finished_step_is_read_only(api, supplier) -> None:
    batch = await api.step1(supplier)
    assert batch["raw_material"]["status"] == "finished"
    assert batch["raw_material"]["finished_by"]["full_name"] == "Test general_manager"
    assert batch["raw_material"]["finished_at"]
    assert batch["current_step"] == 2
    assert_error(
        await api.patch(batch, "raw-material", quantity=3), 409, "PRODUCTION_STEP_FINISHED"
    )
    assert_error(await api.finish(batch, "raw-material"), 409, "PRODUCTION_STEP_FINISHED")


# --- Step dates ----------------------------------------------------------------------------------


async def test_finish_records_the_business_day_for_each_step(api, supplier, clock) -> None:
    clock.at(datetime(2026, 9, 30, 16, 0, tzinfo=UTC))  # 23:00 on 30 Sep in Phnom Penh
    batch = await api.create(supplier_id=supplier["id"], weight_kg="25.5", quantity=10)
    assert batch["code"] == "PR-20260930-001"
    # 17:30 UTC on 30 Sep is already 1 Oct there.
    clock.at(datetime(2026, 9, 30, 17, 30, tzinfo=UTC))
    batch = ok(await api.finish(batch, "raw-material"))
    assert step_dates(batch) == ["2026-10-01", None, None]  # step 2 is a draft: no date yet
    batch = ok(await api.patch(batch, "produced", **PRODUCED))
    clock.at(datetime(2026, 10, 1, 17, 30, tzinfo=UTC))
    batch = ok(await api.finish(batch, "produced"))
    assert step_dates(batch) == ["2026-10-01", "2026-10-02", None]
    batch = ok(await api.patch(batch, "standardize", **standardize_body()))
    clock.at(datetime(2026, 10, 2, 16, 59, tzinfo=UTC))  # 23:59 on 2 Oct there
    batch = ok(await api.finish(batch, "standardize"))
    assert step_dates(batch) == ["2026-10-01", "2026-10-02", "2026-10-02"]
    assert batch["code"] == "PR-20260930-001"  # still the creation day


@pytest.mark.parametrize(
    ("step", "field"),
    [
        ("raw-material", "import_date"),
        ("raw-material", "production_date"),
        ("produced", "production_date"),
        ("standardize", "packaging_date"),
    ],
)
async def test_step_dates_are_never_accepted_from_the_client(api, supplier, step, field) -> None:
    batch = await api.step2(supplier)
    if step == "raw-material":
        batch = ok(await api.reopen(batch, "raw-material"))  # a draft again
    assert_error(await api.patch(batch, step, **{field: "2026-01-01"}), 422, "VALIDATION_ERROR")
    r = await api.client.post(
        f"/production/{batch['id']}/{step}/finish",
        json={"version": batch["version"], field: "2026-01-01"},
        headers=api.headers,
    )
    assert_error(r, 422, "VALIDATION_ERROR")


@pytest.mark.parametrize("field", ["production_date", "import_date"])
async def test_create_rejects_a_date(api, field) -> None:
    r = await api.client.post("/production", json={field: "2026-01-01"}, headers=api.headers)
    assert_error(r, 422, "VALIDATION_ERROR")


async def test_reopen_clears_the_dates_of_reopened_steps(api, supplier, clock) -> None:
    clock.day("2026-06-01")
    batch = await api.step1(supplier)
    clock.day("2026-06-02")
    batch = ok(await api.patch(batch, "produced", **PRODUCED))
    batch = ok(await api.finish(batch, "produced"))
    clock.day("2026-06-03")
    batch = ok(await api.patch(batch, "standardize", **standardize_body()))
    batch = ok(await api.finish(batch, "standardize"))
    assert step_dates(batch) == ["2026-06-01", "2026-06-02", "2026-06-03"]

    clock.day("2026-06-05")
    batch = ok(await api.reopen(batch, "produced"))
    assert step_dates(batch) == ["2026-06-01", None, None]  # step 1 keeps its date
    batch = ok(await api.finish(batch, "produced"))
    assert step_dates(batch) == ["2026-06-01", "2026-06-05", None]
    clock.day("2026-06-06")
    batch = ok(await api.finish(batch, "standardize"))
    assert step_dates(batch) == ["2026-06-01", "2026-06-05", "2026-06-06"]

    batch = ok(await api.reopen(batch, "raw-material"))
    assert step_dates(batch) == [None, None, None]


async def test_step_dates_stay_in_order_through_reopen_sequences(api, supplier, clock) -> None:
    """import ≤ production ≤ packing and nothing in the future, whatever is reopened when."""
    clock.day("2026-07-01")
    batch = await api.create(supplier_id=supplier["id"], weight_kg="25.5", quantity=10)
    script = [
        ("2026-07-01", "finish", "raw-material"),
        ("2026-07-02", "finish", "produced"),
        ("2026-07-03", "reopen", "raw-material"),
        ("2026-07-04", "finish", "raw-material"),
        ("2026-07-04", "finish", "produced"),
        ("2026-07-05", "finish", "standardize"),
        ("2026-07-06", "reopen", "standardize"),
        ("2026-07-07", "reopen", "produced"),
        ("2026-07-08", "finish", "produced"),
        ("2026-07-09", "reopen", "raw-material"),
        ("2026-07-10", "finish", "raw-material"),
        ("2026-07-10", "finish", "produced"),
        ("2026-07-11", "finish", "standardize"),
    ]
    for day, action, step in script:
        clock.day(day)
        if action == "finish" and step == "produced" and batch["produced"]["wings_kg"] is None:
            batch = ok(await api.patch(batch, "produced", **PRODUCED))
        standardize = batch["standardize"]
        if action == "finish" and step == "standardize" and standardize["big_packages"] is None:
            batch = ok(await api.patch(batch, "standardize", **standardize_body()))
        do = api.finish if action == "finish" else api.reopen
        batch = ok(await do(batch, step))
        recorded = [d for d in step_dates(batch) if d is not None]
        assert recorded == sorted(recorded), (day, action, step, recorded)
        assert all(d <= day for d in recorded), (day, action, step, recorded)
        for key in STEP_KEYS:  # finished steps have a date; drafts don't
            if batch[key] is not None:
                finished = batch[key]["status"] == "finished"
                assert finished == (batch[key][DATE_KEYS[key]] is not None), (day, key)
    assert step_dates(batch) == ["2026-07-10", "2026-07-10", "2026-07-11"]


# --- Step 1 --------------------------------------------------------------------------------------


async def test_finish_step_1_requires_every_field(api) -> None:
    batch = await api.create()
    r = await api.finish(batch, "raw-material")
    assert_error(r, 422, "VALIDATION_ERROR")
    assert _field_locs(r) == [
        ["raw_material", "supplier_id"],
        ["raw_material", "weight_kg"],
        ["raw_material", "quantity"],
    ]


async def test_finish_step_1_requires_positive_values(api, supplier) -> None:
    batch = await api.create(supplier_id=supplier["id"], weight_kg="0", quantity=0)
    r = await api.finish(batch, "raw-material")
    assert_error(r, 422, "VALIDATION_ERROR")
    types = {tuple(f["loc"]): f["type"] for f in r.json()["error"]["details"]["fields"]}
    assert types == {
        ("raw_material", "weight_kg"): "greater_than",
        ("raw_material", "quantity"): "greater_than",
    }


async def test_finish_step_1_needs_an_active_supplier(api, client, gm, supplier) -> None:
    batch = await api.create(supplier_id=supplier["id"], weight_kg="5", quantity=2)
    r = await client.post(f"/suppliers/{supplier['id']}/deactivate", headers=auth(gm))
    assert r.status_code == 200
    assert_error(await api.finish(batch, "raw-material"), 422, "SUPPLIER_INACTIVE")


async def test_finishing_step_1_opens_step_2_with_computed_counts(api, supplier) -> None:
    batch = await api.step1(supplier, quantity=10)
    produced = batch["produced"]
    assert produced["status"] == "draft"
    assert (produced["wings_count"], produced["thighs_count"]) == (20, 20)
    assert [b["item_code"] for b in batch["byproducts"]] == BYPRODUCTS
    assert batch["computed"] == {"wings_count": 20, "thighs_count": 20, "yield_percent": None}


# --- Step 2 --------------------------------------------------------------------------------------


@pytest.mark.parametrize("field", ["wings_count", "thighs_count"])
async def test_counts_are_never_accepted_from_the_client(api, supplier, field) -> None:
    batch = await api.step1(supplier)
    assert_error(await api.patch(batch, "produced", **{field: 99}), 422, "VALIDATION_ERROR")


async def test_counts_follow_quantity_after_reopening_step_1(api, supplier) -> None:
    batch = await api.step1(supplier, quantity=10)
    batch = ok(await api.patch(batch, "produced", wings_kg="3"))  # a step 2 draft value
    batch = ok(await api.reopen(batch, "raw-material"))
    assert batch["current_step"] == 1 and batch["raw_material"]["status"] == "draft"
    batch = ok(await api.patch(batch, "raw-material", quantity=12))
    assert batch["produced"]["wings_count"] == 24
    batch = ok(await api.finish(batch, "raw-material"))
    assert (batch["produced"]["wings_count"], batch["produced"]["thighs_count"]) == (24, 24)
    assert batch["produced"]["wings_kg"] == "3.000"  # the step 2 draft is kept


async def test_finish_step_2_validation(api, supplier) -> None:
    batch = await api.step1(supplier)
    batch = ok(await api.patch(batch, "produced", wings_kg="0", byproducts={"liver": "0.3"}))
    r = await api.finish(batch, "produced")
    assert_error(r, 422, "VALIDATION_ERROR")
    assert _field_locs(r) == [
        ["produced", "wings_kg"],
        ["produced", "thighs_kg"],
        ["produced", "marinade_g"],
        ["produced", "byproducts", "gizzard"],
        ["produced", "byproducts", "heart"],
        ["produced", "byproducts", "head"],
    ]


async def test_step_2_accepts_zero_byproducts_and_marinade(api, supplier) -> None:
    batch = await api.step1(supplier)
    body = {**PRODUCED, "marinade_g": 0, "byproducts": {c: 0 for c in BYPRODUCTS}}
    batch = ok(await api.patch(batch, "produced", **body))
    batch = ok(await api.finish(batch, "produced"))
    assert batch["produced"]["status"] == "finished"
    assert batch["produced"]["marinade_g"] == "0.0"
    assert batch["current_step"] == 3
    assert batch["standardize"]["status"] == "draft"


async def test_step_2_values_and_yield(api, supplier) -> None:
    batch = await api.step2(supplier)
    produced = batch["produced"]
    assert (produced["wings_kg"], produced["thighs_kg"], produced["marinade_g"]) == (
        "4.200",
        "6.800",
        "350.0",
    )
    # (4.2 + 6.8) / 25.5 = 43.1 %
    assert batch["computed"]["yield_percent"] == "43.1"
    assert {b["item_code"]: b["produced_kg"] for b in batch["byproducts"]} == {
        c: "0.500" for c in BYPRODUCTS
    }


async def test_unknown_byproduct_is_rejected(api, supplier) -> None:
    batch = await api.step1(supplier)
    r = await api.patch(batch, "produced", byproducts={"feet": "1"})
    assert_error(r, 422, "VALIDATION_ERROR")
    assert _field_locs(r) == [["body", "byproducts", "feet"]]


# --- Step 3 --------------------------------------------------------------------------------------


async def test_finish_step_3_completes_the_batch(api, session, supplier) -> None:
    batch = await api.completed(supplier, comment="  Good batch  ")
    assert batch["status"] == "completed"
    assert batch["completed_at"]
    assert batch["standardize"]["status"] == "finished"
    assert batch["standardize"]["comment"] == "Good batch"
    assert batch["current_step"] == 3

    logs = list(
        await session.scalars(
            select(AuditLog)
            .where(AuditLog.action == "production.step_finish")
            .order_by(AuditLog.id)
        )
    )
    assert [log.details for log in logs] == [{"code": batch["code"], "step": s} for s in (1, 2, 3)]


@pytest.mark.parametrize(
    ("overrides", "wings", "thighs"),
    [
        ({"rejected_wings": 2}, -1, 0),
        ({"rejected_thighs": 0}, 0, 1),
        ({"big": 8}, -2, -2),
        ({"small": 4, "rejected_wings": 2}, 0, 1),
    ],
)
async def test_piece_balance_is_enforced(api, supplier, overrides, wings, thighs) -> None:
    batch = await api.step2(supplier)
    batch = ok(await api.patch(batch, "standardize", **standardize_body(**overrides)))
    r = await api.finish(batch, "standardize")
    assert_error(r, 422, "PRODUCTION_BALANCE_MISMATCH")
    details = r.json()["error"]["details"]
    assert details["wings"]["expected"] == 20
    assert (details["wings"]["difference"], details["thighs"]["difference"]) == (wings, thighs)
    assert details["wings"]["assigned"] == 20 - wings


async def test_byproduct_balance_is_not_enforced_by_the_api(api, supplier) -> None:
    """carry + rejected ≠ produced is a UI-only rule (documented); the API accepts it."""
    body = standardize_body()
    body["byproducts"]["liver"] = {"carry_kg": "9", "rejected_kg": "0"}  # produced 0.5
    batch = await api.step2(supplier)
    batch = ok(await api.patch(batch, "standardize", **body))
    assert ok(await api.finish(batch, "standardize"))["status"] == "completed"


async def test_finish_step_3_requires_every_field(api, supplier) -> None:
    batch = await api.step2(supplier)
    batch = ok(
        await api.patch(
            batch,
            "standardize",
            big_packages=7,
            byproducts={"heart": {"carry_kg": "0.5"}},
        )
    )
    r = await api.finish(batch, "standardize")
    assert_error(r, 422, "VALIDATION_ERROR")
    locs = _field_locs(r)
    assert ["standardize", "small_packages"] in locs
    assert ["standardize", "byproducts", "heart", "rejected_kg"] in locs
    assert ["standardize", "byproducts", "heart", "carry_kg"] not in locs
    assert ["standardize", "big_packages"] not in locs


async def test_step_3_draft_keeps_other_byproduct_fields(api, supplier) -> None:
    batch = await api.step2(supplier)
    batch = ok(await api.patch(batch, "standardize", byproducts={"head": {"carry_kg": "0.2"}}))
    batch = ok(await api.patch(batch, "standardize", byproducts={"head": {"rejected_kg": "0.3"}}))
    head = next(b for b in batch["byproducts"] if b["item_code"] == "head")
    assert (head["produced_kg"], head["carry_kg"], head["rejected_kg"]) == (
        "0.500",
        "0.200",
        "0.300",
    )


# --- Reopen --------------------------------------------------------------------------------------


def _statuses(batch: dict) -> list[str]:
    return [batch[k]["status"] for k in ("raw_material", "produced", "standardize")]


async def test_reopens_steps_in_responses(api, supplier) -> None:
    batch = await api.completed(supplier)
    assert [batch[k]["reopens_steps"] for k in ("raw_material", "produced", "standardize")] == [
        [1, 2, 3],
        [2, 3],
        [3],
    ]
    batch = await api.step1(supplier)
    assert batch["raw_material"]["reopens_steps"] == [1]
    assert batch["produced"]["reopens_steps"] == []  # a draft: nothing to reopen


async def test_editing_step_1_of_a_completed_batch_reopens_everything(
    api, session, supplier
) -> None:
    batch = await api.completed(supplier, comment="Keep me")
    batch = ok(await api.reopen(batch, "raw-material"))
    assert _statuses(batch) == ["draft", "draft", "draft"]
    assert (batch["status"], batch["completed_at"], batch["current_step"]) == (
        "in_progress",
        None,
        1,
    )
    assert all(
        batch[k]["finished_by"] is None and batch[k]["finished_at"] is None
        for k in ("raw_material", "produced", "standardize")
    )
    # Every value is kept.
    assert batch["raw_material"]["quantity"] == 10
    assert batch["produced"]["wings_kg"] == "4.200"
    assert batch["standardize"]["big_packages"] == 7
    assert batch["standardize"]["comment"] == "Keep me"
    assert {b["item_code"]: b["carry_kg"] for b in batch["byproducts"]}["liver"] == "0.400"

    log = await session.scalar(select(AuditLog).where(AuditLog.action == "production.step_reopen"))
    assert log.details == {"code": batch["code"], "step": 1, "reopened_steps": [1, 2, 3]}

    # Later steps are finished again in order; the rules still apply.
    assert_error(await api.finish(batch, "produced"), 409, "PRODUCTION_STEP_NOT_READY")
    assert_error(await api.patch(batch, "produced", wings_kg="1"), 409, "PRODUCTION_STEP_NOT_READY")
    batch = ok(await api.patch(batch, "raw-material", quantity=11))
    batch = ok(await api.finish(batch, "raw-material"))
    assert batch["produced"]["wings_count"] == 22  # recomputed
    batch = ok(await api.finish(batch, "produced"))
    # 20 wings were balanced; 22 now need assigning again.
    assert_error(await api.finish(batch, "standardize"), 422, "PRODUCTION_BALANCE_MISMATCH")
    batch = ok(await api.patch(batch, "standardize", small_packages=7))
    assert ok(await api.finish(batch, "standardize"))["status"] == "completed"


async def test_editing_a_middle_step_keeps_earlier_steps_finished(api, session, supplier) -> None:
    batch = await api.completed(supplier)
    batch = ok(await api.reopen(batch, "produced"))
    assert _statuses(batch) == ["finished", "draft", "draft"]
    assert batch["current_step"] == 2
    log = await session.scalar(select(AuditLog).where(AuditLog.action == "production.step_reopen"))
    assert log.details["reopened_steps"] == [2, 3]


async def test_editing_step_1_while_step_3_is_a_draft(api, supplier) -> None:
    batch = await api.step2(supplier)  # step 3 is an unfinished draft
    batch = ok(await api.reopen(batch, "raw-material"))
    assert _statuses(batch) == ["draft", "draft", "draft"]


async def test_reopen_step_3_puts_the_batch_back_in_progress(api, session, supplier) -> None:
    batch = await api.completed(supplier)
    batch = ok(await api.reopen(batch, "standardize"))
    assert (batch["status"], batch["completed_at"], batch["current_step"]) == (
        "in_progress",
        None,
        3,
    )
    assert batch["standardize"]["status"] == "draft"
    assert batch["standardize"]["finished_by"] is None
    # Then step 2 can be reopened too, and edited again.
    batch = ok(await api.reopen(batch, "produced"))
    assert batch["current_step"] == 2
    batch = ok(await api.patch(batch, "produced", wings_kg="4.5"))
    assert batch["produced"]["wings_kg"] == "4.500"

    logs = list(
        await session.scalars(
            select(AuditLog)
            .where(AuditLog.action == "production.step_reopen")
            .order_by(AuditLog.id)
        )
    )
    assert [(log.details["step"], log.details["reopened_steps"]) for log in logs] == [
        (3, [3]),
        (2, [2]),
    ]


async def test_reopening_a_draft_step_changes_nothing(api) -> None:
    batch = await api.create()
    again = ok(await api.reopen(batch, "raw-material"))
    assert again["version"] == batch["version"]


# --- Cancel --------------------------------------------------------------------------------------


async def test_cancel(api, session, supplier) -> None:
    batch = await api.step1(supplier)
    assert_error(await api.cancel(batch, reason="   "), 422, "VALIDATION_ERROR")
    batch = ok(await api.cancel(batch, reason=" Chickens were sick "))
    assert batch["status"] == "cancelled"
    assert batch["cancel_reason"] == "Chickens were sick"
    assert batch["cancelled_by"]["full_name"] == "Test general_manager"
    assert batch["cancelled_at"]

    # Read-only from now on.
    assert_error(await api.patch(batch, "produced", wings_kg="1"), 409, "PRODUCTION_CANCELLED")
    assert_error(await api.finish(batch, "produced"), 409, "PRODUCTION_CANCELLED")
    assert_error(await api.reopen(batch, "raw-material"), 409, "PRODUCTION_CANCELLED")
    assert_error(await api.cancel(batch), 409, "PRODUCTION_CANCELLED")
    assert (await api.get(batch))["status"] == "cancelled"

    log = await session.scalar(select(AuditLog).where(AuditLog.action == "production.cancel"))
    assert log.details == {"code": batch["code"], "reason": "Chickens were sick"}


async def test_completed_batches_cannot_be_cancelled(api, supplier) -> None:
    batch = await api.completed(supplier)
    assert_error(await api.cancel(batch), 409, "PRODUCTION_COMPLETED")


# --- Stats ---------------------------------------------------------------------------------------


async def test_stats(api, client, gm, supplier, clock) -> None:
    today = production_service.business_today()
    last_month = today.replace(day=1) - timedelta(days=1)
    clock.day(last_month.isoformat())
    await api.step1(supplier, quantity=100)  # imported last month
    clock.at(None)
    await api.completed(supplier, rejected_wings=1, rejected_thighs=1)  # 10 chickens, 2 rejected
    await api.step1(supplier, quantity=5)  # in progress
    await api.create()  # in progress, step 1 draft: its quantity doesn't count
    cancelled = await api.step1(supplier, quantity=7)
    ok(await api.cancel(cancelled))

    stats = ok(await client.get("/production/stats", headers=auth(gm)))
    assert stats == {
        "in_progress": 3,  # incl. last month's batch
        "completed_today": 1,
        "chickens_this_month": 15,
        "rejected_pieces_this_month": 2,
    }


async def test_stats_month_boundary(api, client, gm, supplier, clock) -> None:
    clock.day("2026-09-30")
    await api.step1(supplier, quantity=4)
    clock.day("2026-10-01")
    await api.step1(supplier, quantity=6)
    # 00:30 on 1 Oct in Phnom Penh: September no longer counts.
    clock.at(datetime(2026, 9, 30, 17, 30, tzinfo=UTC))
    stats = ok(await client.get("/production/stats", headers=auth(gm)))
    assert stats["chickens_this_month"] == 6
    # One minute earlier it's still September there.
    clock.at(datetime(2026, 9, 30, 16, 59, tzinfo=UTC))
    stats = ok(await client.get("/production/stats", headers=auth(gm)))
    assert stats["chickens_this_month"] == 4


async def test_stats_use_the_import_and_packing_dates(api, client, gm, supplier, clock) -> None:
    # Imported on 30 Sep; processed and packed on 1 Oct with 3 + 3 rejected pieces.
    clock.day("2026-09-30")
    batch = await api.step1(supplier)
    clock.day("2026-10-01")
    batch = ok(await api.patch(batch, "produced", **PRODUCED))
    batch = ok(await api.finish(batch, "produced"))
    body = standardize_body(small=3, rejected_wings=3, rejected_thighs=3)
    batch = ok(await api.patch(batch, "standardize", **body))
    ok(await api.finish(batch, "standardize"))

    clock.day("2026-10-15")
    stats = ok(await client.get("/production/stats", headers=auth(gm)))
    assert (stats["chickens_this_month"], stats["rejected_pieces_this_month"]) == (0, 6)
    clock.day("2026-09-15")
    stats = ok(await client.get("/production/stats", headers=auth(gm)))
    assert (stats["chickens_this_month"], stats["rejected_pieces_this_month"]) == (10, 0)


# --- List and supplier options -------------------------------------------------------------------


async def _list(client, gm, **params) -> dict:
    return ok(await client.get("/production", params=params, headers=auth(gm)))


async def test_list_filters(api, client, gm, supplier, clock) -> None:
    other = ok(
        await client.post("/suppliers", json={"name": "Dara Poultry"}, headers=auth(gm)), 201
    )
    clock.day("2026-04-01")
    draft = await api.create()
    clock.day("2026-04-02")
    waiting2 = await api.step1(supplier)
    clock.day("2026-04-03")
    waiting3 = await api.step2(other)
    clock.day("2026-04-04")
    cancelled = await api.step1(supplier)
    ok(await api.cancel(cancelled))

    def codes(page: dict) -> list[str]:
        return [item["code"] for item in page["items"]]

    page = await _list(client, gm)
    # Cancelled batches are left out by default; latest date first.
    assert page["total"] == 3 and page["page_size"] == 20
    assert codes(page) == [b["code"] for b in (waiting3, waiting2, draft)]
    assert codes(await _list(client, gm, sort="date"))[0] == draft["code"]
    # ...and shown when asked for, alone or added to a status.
    page = await _list(client, gm, include_cancelled="true")
    assert codes(page) == [b["code"] for b in (cancelled, waiting3, waiting2, draft)]
    assert set(codes(await _list(client, gm, status="in_progress", include_cancelled="true"))) == {
        draft["code"],
        waiting2["code"],
        waiting3["code"],
        cancelled["code"],
    }
    assert codes(await _list(client, gm, q="20260404")) == []
    assert codes(await _list(client, gm, q="20260404", include_cancelled="true")) == [
        cancelled["code"]
    ]

    assert codes(await _list(client, gm, waiting_step=2)) == [waiting2["code"]]
    assert codes(await _list(client, gm, waiting_step=3)) == [waiting3["code"]]
    assert codes(await _list(client, gm, status="cancelled")) == [cancelled["code"]]
    assert set(codes(await _list(client, gm, status="in_progress"))) == {
        draft["code"],
        waiting2["code"],
        waiting3["code"],
    }
    assert codes(await _list(client, gm, date_from="2026-04-02", date_to="2026-04-03")) == [
        waiting3["code"],
        waiting2["code"],
    ]
    assert codes(await _list(client, gm, q="dara")) == [waiting3["code"]]
    assert codes(await _list(client, gm, q="20260401")) == [draft["code"]]
    assert codes(await _list(client, gm, page_size=1, page=2)) == [waiting2["code"]]

    item = (await _list(client, gm, waiting_step=3))["items"][0]
    assert item["steps"] == ["finished", "finished", "draft"]
    assert (item["import_date"], item["production_date"], item["packaging_date"]) == (
        "2026-04-03",
        "2026-04-03",
        None,
    )
    assert item["created_at"]
    assert item["supplier"]["name"] == "Dara Poultry"
    assert item["quantity"] == 10
    assert (await _list(client, gm, q=draft["code"]))["items"][0]["steps"] == [
        "draft",
        "pending",
        "pending",
    ]
    assert_error(
        await client.get("/production?waiting_step=1", headers=auth(gm)), 422, "VALIDATION_ERROR"
    )


async def test_list_dates_filter_and_sort(api, client, gm, supplier, clock) -> None:
    """The date filter matches any step date (the creation day while nothing is finished); the
    date sort uses the latest recorded date."""
    # A: created 1 May, imported 2 May, processed 5 May, packed 9 May.
    clock.day("2026-05-01")
    a = await api.create(supplier_id=supplier["id"], weight_kg="25.5", quantity=10)
    clock.day("2026-05-02")
    a = ok(await api.finish(a, "raw-material"))
    clock.day("2026-05-05")
    a = ok(await api.patch(a, "produced", **PRODUCED))
    a = ok(await api.finish(a, "produced"))
    clock.day("2026-05-09")
    a = ok(await api.patch(a, "standardize", **standardize_body()))
    a = ok(await api.finish(a, "standardize"))
    # B: created and imported 6 May.
    clock.day("2026-05-06")
    b = await api.step1(supplier)
    # C: created 7 May, nothing finished.
    clock.day("2026-05-07")
    c = await api.create()

    def codes(page: dict) -> list[str]:
        return [item["code"] for item in page["items"]]

    # Latest dates: A 9 May, C 7 May (creation day), B 6 May.
    assert codes(await _list(client, gm)) == [a["code"], c["code"], b["code"]]
    assert codes(await _list(client, gm, sort="date")) == [b["code"], c["code"], a["code"]]

    async def matching(date_from: str | None, date_to: str | None) -> set[str]:
        params = {k: v for k, v in (("date_from", date_from), ("date_to", date_to)) if v}
        return set(codes(await _list(client, gm, **params)))

    assert await matching("2026-05-05", "2026-05-05") == {a["code"]}  # A's production date
    assert await matching("2026-05-01", "2026-05-01") == set()  # A's creation day: not a step date
    assert await matching("2026-05-03", "2026-05-04") == set()  # between A's step dates
    assert await matching("2026-05-06", "2026-05-06") == {b["code"]}
    assert await matching("2026-05-07", "2026-05-07") == {c["code"]}  # C's creation day
    assert await matching("2026-05-08", None) == {a["code"]}
    assert await matching(None, "2026-05-02") == {a["code"]}
    # Once C's step 1 is finished, its creation day no longer counts.
    clock.day("2026-05-12")
    c = ok(
        await api.patch(c, "raw-material", supplier_id=supplier["id"], weight_kg="5", quantity=2)
    )
    ok(await api.finish(c, "raw-material"))
    assert await matching("2026-05-07", "2026-05-07") == set()
    assert codes(await _list(client, gm))[0] == c["code"]


async def test_supplier_options(client, gm) -> None:
    for name, phone in (("Sokha Farm", "012345678"), ("Dara Poultry", None), ("Old Farm", None)):
        r = await client.post("/suppliers", json={"name": name, "phone": phone}, headers=auth(gm))
        created = ok(r, 201)
        if name == "Old Farm":
            await client.post(f"/suppliers/{created['id']}/deactivate", headers=auth(gm))

    options = ok(await client.get("/production/supplier-options", headers=auth(gm)))
    assert [o["name"] for o in options] == ["Dara Poultry", "Sokha Farm"]
    assert set(options[0]) == {"id", "name", "phone_display"}
    options = ok(await client.get("/production/supplier-options?q=012 34", headers=auth(gm)))
    assert [o["name"] for o in options] == ["Sokha Farm"]
    assert options[0]["phone_display"] == "012 345 678"


# --- Audit link ----------------------------------------------------------------------------------


async def test_audit_entries_link_to_the_batch(api, client, gm, supplier) -> None:
    batch = await api.step1(supplier)
    r = await client.get(
        "/audit-logs", params={"entity_type": "production_batch"}, headers=auth(gm)
    )
    items = ok(r)["items"]
    assert [i["action"] for i in items] == ["production.step_finish", "production.create"]
    assert all(
        i["entity"] == {"type": "production_batch", "id": batch["id"], "name": batch["code"]}
        for i in items
    )


def test_business_today_uses_the_timezone() -> None:
    assert production_service.business_today(datetime(2026, 1, 1, 17, 0, tzinfo=UTC)) == date(
        2026, 1, 2
    )
