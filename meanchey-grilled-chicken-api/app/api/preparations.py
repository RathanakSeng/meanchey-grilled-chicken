"""Preparations: satay sachets and packaging materials (services/preparation_service.py)."""

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request, status

from app.bot.notify import deliver
from app.deps import SessionDep, require_permission
from app.models import User
from app.schemas.preparation import (
    CancelIn,
    PreparationCreate,
    PreparationDraft,
    PreparationListStatus,
    PreparationMaterialOut,
    PreparationOut,
    PreparationPage,
    PreparationStats,
    PreparationType,
    VersionIn,
)
from app.services import notification_service
from app.services import preparation_service as svc

router = APIRouter(prefix="/preparations", tags=["preparations"])

CanView = Annotated[User, Depends(require_permission("preparation.view"))]
CanRecord = Annotated[User, Depends(require_permission("preparation.create"))]
CanReopen = Annotated[User, Depends(require_permission("preparation.update"))]
CanCancel = Annotated[User, Depends(require_permission("preparation.cancel"))]


@router.get("", response_model=PreparationPage)
async def list_preparations(
    _: CanView,
    session: SessionDep,
    type: PreparationType | None = None,
    status: PreparationListStatus = "all",
    include_cancelled: bool = False,
    date_from: date | None = None,
    date_to: date | None = None,
    q: Annotated[str | None, Query(max_length=100)] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> PreparationPage:
    """Cancelled preparations are left out unless `include_cancelled=true` or `status=cancelled`.
    `date_from` / `date_to`: the prepared date, or the creation day while not finished. `q`
    matches the code and material names. Newest first."""
    rows, total = await svc.list_preparations(
        session,
        type_=type,
        status=status,
        include_cancelled=include_cancelled,
        date_from=date_from,
        date_to=date_to,
        q=q,
        page=page,
        page_size=page_size,
    )
    return PreparationPage(
        items=await svc.list_items(session, rows), total=total, page=page, page_size=page_size
    )


# Declared before /{preparation_id} so these aren't parsed as UUIDs.
@router.get("/stats", response_model=PreparationStats)
async def get_stats(_: CanView, session: SessionDep) -> PreparationStats:
    """Drafts now; finished preparations and sachets made this month (BUSINESS_TIMEZONE)."""
    return await svc.stats(session)


@router.get("/material-options", response_model=list[PreparationMaterialOut])
async def material_options(_: CanRecord, session: SessionDep) -> list[PreparationMaterialOut]:
    """Active packaging materials (preparable 1:1) with their stock (no Inventory access
    needed)."""
    return await svc.material_options(session)


@router.post("", response_model=PreparationOut, status_code=status.HTTP_201_CREATED)
async def create_preparation(
    body: PreparationCreate, actor: CanRecord, session: SessionDep
) -> PreparationOut:
    p = await svc.create_preparation(session, actor, body)
    return await svc.preparation_out(session, p)


@router.get("/{preparation_id}", response_model=PreparationOut)
async def get_preparation(
    preparation_id: uuid.UUID, _: CanView, session: SessionDep
) -> PreparationOut:
    return await svc.preparation_out(session, await svc.get_preparation(session, preparation_id))


@router.patch("/{preparation_id}", response_model=PreparationOut)
async def save_draft(
    preparation_id: uuid.UUID, body: PreparationDraft, actor: CanRecord, session: SessionDep
) -> PreparationOut:
    """Draft save: `lines` replaces every line (partial values allowed); `version` required."""
    p = await svc.save_draft(session, actor, preparation_id, body)
    return await svc.preparation_out(session, p)


@router.post("/{preparation_id}/finish", response_model=PreparationOut)
async def finish(
    preparation_id: uuid.UUID,
    body: VersionIn,
    actor: CanRecord,
    session: SessionDep,
    request: Request,
    background: BackgroundTasks,
) -> PreparationOut:
    """Validate strictly, move the stock and lock the preparation. The managers' alert is stored
    now and sent to Telegram after the response."""
    try:
        p = await svc.finish(session, actor, preparation_id, body.version)
    except Exception:
        notification_service.discard_queued(session)
        raise
    ids = notification_service.take_queued(session)
    if ids:
        background.add_task(deliver, ids, request.app.state.telegram)
    return await svc.preparation_out(session, p)


@router.post("/{preparation_id}/reopen", response_model=PreparationOut)
async def reopen(
    preparation_id: uuid.UUID, body: VersionIn, actor: CanReopen, session: SessionDep
) -> PreparationOut:
    """Back to draft (values kept); its stock movements are reversed."""
    p = await svc.reopen(session, actor, preparation_id, body.version)
    return await svc.preparation_out(session, p)


@router.post("/{preparation_id}/cancel", response_model=PreparationOut)
async def cancel(
    preparation_id: uuid.UUID, body: CancelIn, actor: CanCancel, session: SessionDep
) -> PreparationOut:
    """A draft or a finished preparation (its stock reversed first); read-only afterwards."""
    p = await svc.cancel(session, actor, preparation_id, body.version, body.reason)
    return await svc.preparation_out(session, p)
