"""Inventory: balances, the movement history and adjustments (services/inventory_service.py)."""

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.deps import SessionDep, require_permission
from app.inventory.catalog import Section
from app.models import User
from app.schemas.inventory import (
    InventoryItemOut,
    InventoryOut,
    MovementPage,
    MovementSource,
    SetValueIn,
)
from app.services import inventory_service as svc

router = APIRouter(prefix="/inventory", tags=["inventory"])

CanView = Annotated[User, Depends(require_permission("inventory.view"))]
CanAdjust = Annotated[User, Depends(require_permission("inventory.adjust"))]


@router.get("", response_model=InventoryOut)
async def overview(_: CanView, session: SessionDep) -> InventoryOut:
    """Every catalog item's balance, grouped by section (stock, then wasted)."""
    return await svc.overview(session)


@router.get("/movements", response_model=MovementPage)
async def movements(
    _: CanView,
    session: SessionDep,
    item_code: Annotated[str | None, Query(max_length=64)] = None,
    section: Section | None = None,
    source: MovementSource | None = None,
    batch_id: uuid.UUID | None = None,
    batch_code: Annotated[str | None, Query(max_length=32)] = None,
    date_from: date | None = None,
    date_to: date | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = svc.MOVEMENTS_PAGE_SIZE,
) -> MovementPage:
    """Newest first. Dates are business days (BUSINESS_TIMEZONE); `batch_code` matches part of
    the batch code."""
    return await svc.movements(
        session,
        item_code=item_code,
        section=section,
        source=source,
        batch_id=batch_id,
        batch_code=batch_code,
        date_from=date_from,
        date_to=date_to,
        page=page,
        page_size=page_size,
    )


@router.post("/items/{item_code}/set", response_model=InventoryItemOut)
async def set_value(
    item_code: str, body: SetValueIn, actor: CanAdjust, session: SessionDep
) -> InventoryItemOut:
    """Set the item's stock to the given count / kg (one adjustment movement of the difference,
    audited). Only units the item tracks; values >= 0; a reason is required."""
    await svc.set_value(session, actor, item_code, body)
    await session.commit()
    overview = await svc.overview(session)
    return next(i for s in overview.sections for i in s.items if i.code == item_code)
