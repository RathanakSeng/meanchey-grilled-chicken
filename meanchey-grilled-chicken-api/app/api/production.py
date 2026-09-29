"""Production batches (see services/production_service.py for the rules)."""

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.deps import SessionDep, require_permission
from app.models import User
from app.schemas.production import (
    BatchOut,
    BatchPage,
    CancelIn,
    ListStatus,
    ProducedDraft,
    ProductionCreate,
    ProductionSort,
    ProductionStats,
    RawMaterialDraft,
    StandardizeDraft,
    StepSlug,
    SupplierOption,
    VersionIn,
)
from app.services import production_service as svc

router = APIRouter(prefix="/production", tags=["production"])

CanView = Annotated[User, Depends(require_permission("production.view"))]
CanRecord = Annotated[User, Depends(require_permission("production.create"))]
CanReopen = Annotated[User, Depends(require_permission("production.update"))]
CanCancel = Annotated[User, Depends(require_permission("production.delete"))]


@router.get("", response_model=BatchPage)
async def list_batches(
    _: CanView,
    session: SessionDep,
    status: ListStatus = "all",
    include_cancelled: bool = False,
    waiting_step: Annotated[int | None, Query(ge=2, le=3)] = None,
    date_from: date | None = None,
    date_to: date | None = None,
    q: Annotated[str | None, Query(max_length=100)] = None,
    sort: ProductionSort = "-date",
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> BatchPage:
    """Cancelled batches are left out unless `include_cancelled=true` (then they're added to the
    chosen status) or `status=cancelled` (only them). `waiting_step=2|3`: in-progress batches
    whose previous steps are finished and that step isn't. `q` matches the batch code and the
    supplier name. `date_from`/`date_to`: a batch matches if any of its step dates (import,
    production, packing) is in the range or, while no step is finished, its creation day.
    `date` sort: by the latest recorded step date (else the creation day), then the code."""
    items, total = await svc.list_batches(
        session,
        status=status,
        include_cancelled=include_cancelled,
        waiting_step=waiting_step,
        date_from=date_from,
        date_to=date_to,
        q=q,
        sort=sort,
        page=page,
        page_size=page_size,
    )
    return BatchPage(
        items=await svc.list_items(session, items), total=total, page=page, page_size=page_size
    )


# Declared before /{batch_id} so these aren't parsed as UUIDs.
@router.get("/stats", response_model=ProductionStats)
async def get_stats(_: CanView, session: SessionDep) -> ProductionStats:
    """KPI figures in BUSINESS_TIMEZONE; cancelled batches are excluded."""
    return await svc.stats(session)


@router.get("/supplier-options", response_model=list[SupplierOption])
async def supplier_options(
    _: CanRecord,
    session: SessionDep,
    q: Annotated[str | None, Query(max_length=100)] = None,
) -> list[SupplierOption]:
    """Active suppliers to pick in step 1 (no Suppliers permission needed)."""
    return await svc.supplier_options(session, q)


@router.post("", response_model=BatchOut, status_code=status.HTTP_201_CREATED)
async def create_batch(body: ProductionCreate, actor: CanRecord, session: SessionDep) -> BatchOut:
    batch = await svc.create_batch(session, actor, body)
    return await svc.batch_out(session, batch)


@router.get("/{batch_id}", response_model=BatchOut)
async def get_batch(batch_id: uuid.UUID, _: CanView, session: SessionDep) -> BatchOut:
    return await svc.batch_out(session, await svc.get_batch(session, batch_id))


@router.patch("/{batch_id}/raw-material", response_model=BatchOut)
async def save_raw_material(
    batch_id: uuid.UUID, body: RawMaterialDraft, actor: CanRecord, session: SessionDep
) -> BatchOut:
    """Draft save of step 1. Partial body; `version` is required."""
    batch = await svc.save_raw_material(session, actor, batch_id, body, body.version)
    return await svc.batch_out(session, batch)


@router.patch("/{batch_id}/produced", response_model=BatchOut)
async def save_produced(
    batch_id: uuid.UUID, body: ProducedDraft, actor: CanRecord, session: SessionDep
) -> BatchOut:
    """Draft save of step 2 (step 1 must be finished). Piece counts are computed, not sent."""
    return await svc.batch_out(session, await svc.save_produced(session, actor, batch_id, body))


@router.patch("/{batch_id}/standardize", response_model=BatchOut)
async def save_standardize(
    batch_id: uuid.UUID, body: StandardizeDraft, actor: CanRecord, session: SessionDep
) -> BatchOut:
    """Draft save of step 3 (step 2 must be finished)."""
    return await svc.batch_out(session, await svc.save_standardize(session, actor, batch_id, body))


@router.post("/{batch_id}/{step}/finish", response_model=BatchOut)
async def finish_step(
    batch_id: uuid.UUID, step: StepSlug, body: VersionIn, actor: CanRecord, session: SessionDep
) -> BatchOut:
    """Validate strictly and lock the step. Finishing standardize completes the batch."""
    batch = await svc.finish_step(session, actor, batch_id, svc.STEP_NUMBERS[step], body.version)
    return await svc.batch_out(session, batch)


@router.post("/{batch_id}/{step}/reopen", response_model=BatchOut)
async def reopen_step(
    batch_id: uuid.UUID, step: StepSlug, body: VersionIn, actor: CanReopen, session: SessionDep
) -> BatchOut:
    """Reopen a finished step: it and every later finished step go back to draft (values kept),
    `current_step` becomes this step and a completed batch is in progress again."""
    batch = await svc.reopen_step(session, actor, batch_id, svc.STEP_NUMBERS[step], body.version)
    return await svc.batch_out(session, batch)


@router.post("/{batch_id}/cancel", response_model=BatchOut)
async def cancel_batch(
    batch_id: uuid.UUID, body: CancelIn, actor: CanCancel, session: SessionDep
) -> BatchOut:
    batch = await svc.cancel_batch(session, actor, batch_id, body.reason, body.version)
    return await svc.batch_out(session, batch)
