"""Production request/response models.

Weights are `Decimal`, never float. They are accepted as JSON numbers or strings and always
returned as fixed-precision strings: kilograms with 3 decimals ("12.500"), grams with 1 ("350.0").
Draft bodies are partial: only the fields present are applied, `null` clears a value. Piece counts
are computed by the server and not accepted (`extra="forbid"` rejects them), and so are the step
dates: each is recorded by the server when its step is finished.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, PlainSerializer

from app.models.production import (
    CANCEL_REASON_MAX_LENGTH,
    COMMENT_MAX_LENGTH,
    PLAN_NOTE_MAX_LENGTH,
)
from app.schemas.common import UserRef

MAX_COUNT = 1_000_000

KgIn = Annotated[Decimal, Field(ge=0, max_digits=10, decimal_places=3)]
GramsIn = Annotated[Decimal, Field(ge=0, max_digits=10, decimal_places=1)]
CountIn = Annotated[int, Field(ge=0, le=MAX_COUNT)]
Version = Annotated[int, Field(ge=1)]

KgOut = Annotated[Decimal, PlainSerializer(lambda v: f"{v:.3f}", return_type=str)]
GramsOut = Annotated[Decimal, PlainSerializer(lambda v: f"{v:.1f}", return_type=str)]

StepSlug = Literal["raw-material", "produced", "standardize"]
BatchStatus = Literal["in_progress", "completed", "cancelled"]
StepStatus = Literal["draft", "finished"]
ListStatus = Literal["in_progress", "completed", "cancelled", "all"]
ProductionSort = Literal["date", "-date", "code", "-code"]
# "2" / "3": the previous steps are finished and that step isn't (step 3: the plan is confirmed);
# "plan": step 2 is finished and the packaging plan is still pending.
WaitingStep = Literal["2", "3", "plan"]
PlanStatus = Literal["pending", "confirmed"]
PlanListStatus = Literal["pending", "confirmed", "completed", "all"]


def _reason(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("Reason is required")
    return value


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --- Requests ------------------------------------------------------------------------------------


class RawMaterialFields(_Body):
    supplier_id: uuid.UUID | None = None
    material_kind: Annotated[str, Field(max_length=32)] | None = None
    weight_kg: KgIn | None = None
    quantity: CountIn | None = None


class ProductionCreate(RawMaterialFields):
    """Optional initial step 1 values. The code is numbered per creation day (BUSINESS_TIMEZONE)."""


class RawMaterialDraft(RawMaterialFields):
    version: Version


class ProducedDraft(_Body):
    version: Version
    wings_kg: KgIn | None = None
    thighs_kg: KgIn | None = None
    marinade_g: GramsIn | None = None
    # item_code -> produced kg.
    byproducts: dict[str, KgIn | None] | None = None


class ByproductDispositionIn(_Body):
    carry_kg: KgIn | None = None
    rejected_kg: KgIn | None = None


class StandardizeDraft(_Body):
    version: Version
    big_packages: CountIn | None = None
    small_packages: CountIn | None = None
    rejected_wings: CountIn | None = None
    rejected_thighs: CountIn | None = None
    comment: Annotated[str, Field(max_length=COMMENT_MAX_LENGTH)] | None = None
    # item_code -> carried forward / rejected kg.
    byproducts: dict[str, ByproductDispositionIn] | None = None


class PlanUpdate(_Body):
    """Partial: only fields present are applied; `null` clears one (not on a confirmed plan)."""

    version: Version
    # 4-piece packs (2 wings + 2 thighs each) and 2-piece packs (1 wing + 1 thigh each).
    expected_big: CountIn | None = None
    expected_small: CountIn | None = None
    note: Annotated[str, Field(max_length=PLAN_NOTE_MAX_LENGTH)] | None = None


class VersionIn(_Body):
    version: Version


class CancelIn(_Body):
    version: Version
    reason: Annotated[
        str, Field(min_length=1, max_length=CANCEL_REASON_MAX_LENGTH), AfterValidator(_reason)
    ]


# --- Responses -----------------------------------------------------------------------------------


class SupplierBrief(BaseModel):
    id: uuid.UUID
    name: str
    phone_display: str | None
    is_active: bool


class SupplierOption(BaseModel):
    id: uuid.UUID
    name: str
    phone_display: str | None


class _StepOut(BaseModel):
    status: StepStatus
    # Reopening this step puts these steps back to draft: itself and every later
    # finished step. Empty when the step isn't finished or the batch is cancelled.
    reopens_steps: list[int]
    finished_by: UserRef | None
    finished_at: datetime | None
    updated_by: UserRef | None
    updated_at: datetime


class RawMaterialOut(_StepOut):
    supplier: SupplierBrief | None
    material_kind: str
    weight_kg: KgOut | None
    quantity: int | None
    # ថ្ងៃនាំចូល: recorded when step 1 is finished (today, BUSINESS_TIMEZONE); null while a draft.
    import_date: date | None


class ProducedOut(_StepOut):
    wings_kg: KgOut | None
    thighs_kg: KgOut | None
    # Computed by the server: quantity × pieces per unit (2 for chicken).
    wings_count: int
    thighs_count: int
    marinade_g: GramsOut | None
    # ថ្ងៃផលិត: recorded when step 2 is finished; null while a draft.
    production_date: date | None


class StandardizeOut(_StepOut):
    big_packages: int | None
    small_packages: int | None
    rejected_wings: int | None
    rejected_thighs: int | None
    comment: str | None
    # ថ្ងៃវេចខ្ចប់: recorded when step 3 is finished; null while a draft.
    packaging_date: date | None
    # Both pack counts equal the plan's; null until both actual counts (and a plan) exist.
    plan_matches: bool | None


class PlanOut(BaseModel):
    """The packaging plan as shown on a batch (read-only there)."""

    status: PlanStatus
    expected_big: int | None
    expected_small: int | None
    note: str | None
    confirmed_by: UserRef | None
    confirmed_at: datetime | None
    updated_by: UserRef | None
    updated_at: datetime


class ByproductOut(BaseModel):
    item_code: str
    produced_kg: KgOut | None
    carry_kg: KgOut | None
    rejected_kg: KgOut | None


class ComputedOut(BaseModel):
    # Expected pieces from the current step 1 quantity (0 while it's empty).
    wings_count: int
    thighs_count: int
    # (wings kg + thighs kg) ÷ raw kg × 100, one decimal; null until both are known.
    yield_percent: str | None


class ByproductCatalogOut(BaseModel):
    code: str
    name_en: str
    name_km: str
    unit: str
    order: int


class MaterialKindCatalogOut(BaseModel):
    code: str
    name_en: str
    name_km: str
    wings_per_unit: int
    thighs_per_unit: int


class CatalogOut(BaseModel):
    byproducts: list[ByproductCatalogOut]
    material_kinds: list[MaterialKindCatalogOut]


class BatchOut(BaseModel):
    id: uuid.UUID
    code: str
    status: BatchStatus
    current_step: int
    version: int
    cancel_reason: str | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None
    cancelled_at: datetime | None
    created_by: UserRef | None
    updated_by: UserRef | None
    cancelled_by: UserRef | None
    raw_material: RawMaterialOut
    # null until the previous step is finished for the first time.
    produced: ProducedOut | None
    standardize: StandardizeOut | None
    # The packaging plan (created when step 2 is finished); null before that, and for batches
    # finished before plans existed (then `plan_legacy` is true).
    plan: PlanOut | None
    plan_legacy: bool
    byproducts: list[ByproductOut]
    computed: ComputedOut
    catalog: CatalogOut


class BatchListItem(BaseModel):
    id: uuid.UUID
    code: str
    # The three step dates; null until that step is finished.
    import_date: date | None
    production_date: date | None
    packaging_date: date | None
    created_at: datetime
    status: BatchStatus
    current_step: int
    # Status of steps 1–3: "draft", "finished", or "pending" (not started yet).
    steps: list[Literal["pending", "draft", "finished"]]
    supplier: SupplierBrief | None
    material_kind: str
    quantity: int | None
    created_by: UserRef | None
    updated_at: datetime


class BatchPage(BaseModel):
    items: list[BatchListItem]
    total: int
    page: int
    page_size: int


class ProductionStats(BaseModel):
    in_progress: int
    # Batches completed today (BUSINESS_TIMEZONE).
    completed_today: int
    # Chickens (step 1 quantity) of finished step 1s whose import date is this month;
    # cancelled batches excluded.
    chickens_this_month: int
    # Rejected wings + thighs of finished step 3s whose packing date is this month; cancelled
    # batches excluded.
    rejected_pieces_this_month: int


# --- Packaging plans -----------------------------------------------------------------------------


class PlanListItem(BaseModel):
    batch_id: uuid.UUID
    code: str
    batch_status: BatchStatus
    supplier: SupplierBrief | None
    # ថ្ងៃផលិត (step 2); null while step 2 is back in draft after a reopen.
    production_date: date | None
    quantity: int | None
    wings_count: int
    thighs_count: int
    status: PlanStatus
    expected_big: int | None
    expected_small: int | None
    updated_at: datetime


class PlanPage(BaseModel):
    items: list[PlanListItem]
    total: int
    page: int
    page_size: int
    # Plans waiting to be set (pending, batch in progress), whatever the filter.
    pending_count: int


class ProducedByproductOut(BaseModel):
    item_code: str
    name_en: str
    name_km: str
    produced_kg: KgOut | None


class ProducedSummary(BaseModel):
    """Step 2 as the planner sees it."""

    status: StepStatus
    production_date: date | None
    wings_kg: KgOut | None
    thighs_kg: KgOut | None
    wings_count: int
    thighs_count: int
    marinade_g: GramsOut | None
    byproducts: list[ProducedByproductOut]


class ActualPacks(BaseModel):
    """Step 3's pack counts, once there are any."""

    status: StepStatus
    big_packages: int | None
    small_packages: int | None
    comment: str | None
    packaging_date: date | None


class PlanDetail(BaseModel):
    batch_id: uuid.UUID
    code: str
    batch_status: BatchStatus
    current_step: int
    # The batch version: every plan write sends it (PRODUCTION_CONFLICT when stale).
    version: int
    supplier: SupplierBrief | None
    quantity: int | None
    produced: ProducedSummary | None
    standardize: ActualPacks | None
    plan: PlanOut | None
    plan_legacy: bool
    # The plan can be changed now (step 2 finished, step 3 not finished, batch not cancelled);
    # the caller still needs production_plan.manage.
    editable: bool
