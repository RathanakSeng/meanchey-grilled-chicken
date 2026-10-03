"""Orders (see services/order_service.py for the rules)."""

import uuid
from collections.abc import Awaitable
from datetime import date
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.notify import deliver
from app.deps import SessionDep, require_any_permission, require_permission
from app.models import Order, User
from app.schemas.order import (
    AvailableItem,
    CustomerOption,
    DeliveredIn,
    DriverOption,
    OrderCancelIn,
    OrderCreate,
    OrderListStatus,
    OrderOut,
    OrderPage,
    OrderStats,
    OrderUpdate,
    OrderVersionIn,
    ReviewIn,
)
from app.services import notification_service
from app.services import order_service as svc

router = APIRouter(prefix="/orders", tags=["orders"])

CanView = Annotated[User, Depends(require_permission("orders.view"))]
CanRecord = Annotated[User, Depends(require_permission("orders.create"))]
CanEdit = Annotated[User, Depends(require_permission("orders.update"))]
CanCancel = Annotated[User, Depends(require_permission("orders.cancel"))]
CanReview = Annotated[User, Depends(require_permission("orders.review_returns"))]
# The pickers of the order form (create or edit); no Customers access needed.
CanFillForm = Annotated[User, Depends(require_any_permission("orders.create", "orders.update"))]


async def _alerting(
    session: AsyncSession, request: Request, background: BackgroundTasks, action: Awaitable[Order]
) -> Order:
    """Run a write that may create alerts; send them to Telegram after the response."""
    try:
        order = await action
    except Exception:
        notification_service.discard_queued(session)
        raise
    ids = notification_service.take_queued(session)
    if ids:
        background.add_task(deliver, ids, request.app.state.telegram)
    return order


@router.get("", response_model=OrderPage)
async def list_orders(
    _: CanView,
    session: SessionDep,
    status: OrderListStatus = "all",
    customer_id: uuid.UUID | None = None,
    driver_id: uuid.UUID | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    q: Annotated[str | None, Query(max_length=100)] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> OrderPage:
    """Newest delivery date first. `status=completed`: success, partly and fully returned.
    `date_from` / `date_to` filter the delivery date; `q` matches the code and the customer."""
    items, total = await svc.list_orders(
        session,
        status=status,
        customer_id=customer_id,
        driver_id=driver_id,
        date_from=date_from,
        date_to=date_to,
        q=q,
        page=page,
        page_size=page_size,
    )
    return OrderPage(items=items, total=total, page=page, page_size=page_size)


# Declared before /{order_id} so these aren't parsed as UUIDs.
@router.get("/stats", response_model=OrderStats)
async def get_stats(_: CanView, session: SessionDep) -> OrderStats:
    """Created, delivering, return pending (now) and delivered this month (BUSINESS_TIMEZONE)."""
    return await svc.stats(session)


@router.get("/customer-options", response_model=list[CustomerOption])
async def customer_options(
    _: CanFillForm, session: SessionDep, q: Annotated[str | None, Query(max_length=100)] = None
) -> list[CustomerOption]:
    """Active customers to pick (name or phone digits), at most 20."""
    return await svc.customer_options(session, q)


@router.get("/driver-options", response_model=list[DriverOption])
async def driver_options(_: CanFillForm, session: SessionDep) -> list[DriverOption]:
    """Active staff and supervisors."""
    return await svc.driver_options(session)


@router.get("/available-stock", response_model=list[AvailableItem])
async def available_stock(_: CanFillForm, session: SessionDep) -> list[AvailableItem]:
    """Current stock of the items an order can contain (packs, packed by-products)."""
    return await svc.available_stock(session)


@router.post("", response_model=OrderOut, status_code=status.HTTP_201_CREATED)
async def create_order(body: OrderCreate, actor: CanRecord, session: SessionDep) -> OrderOut:
    """Stock is not touched (it leaves at Delivering); `stock_warnings` lists items whose stock
    is below the order's totals right now."""
    return await svc.order_out(session, await svc.create_order(session, actor, body))


@router.get("/{order_id}", response_model=OrderOut)
async def get_order(order_id: uuid.UUID, _: CanView, session: SessionDep) -> OrderOut:
    return await svc.order_out(session, await svc.get_order(session, order_id))


@router.patch("/{order_id}", response_model=OrderOut)
async def update_order(
    order_id: uuid.UUID, body: OrderUpdate, actor: CanEdit, session: SessionDep
) -> OrderOut:
    """Created orders only. Partial; `boxes` replaces every box and line."""
    return await svc.order_out(session, await svc.update_order(session, actor, order_id, body))


@router.post("/{order_id}/cancel", response_model=OrderOut)
async def cancel_order(
    order_id: uuid.UUID, body: OrderCancelIn, actor: CanCancel, session: SessionDep
) -> OrderOut:
    """The customer cancelled (Created orders only); a reason is required."""
    order = await svc.cancel_order(session, actor, order_id, body.version, body.reason)
    return await svc.order_out(session, order)


@router.post("/{order_id}/delivering", response_model=OrderOut)
async def start_delivery(
    order_id: uuid.UUID,
    body: OrderVersionIn,
    actor: CanRecord,
    session: SessionDep,
    request: Request,
    background: BackgroundTasks,
) -> OrderOut:
    """Created → delivering: the order's totals leave stock, oldest batch first
    (INVENTORY_INSUFFICIENT keeps it Created)."""
    order = await _alerting(
        session, request, background, svc.start_delivery(session, actor, order_id, body.version)
    )
    return await svc.order_out(session, order)


@router.post("/{order_id}/delivered", response_model=OrderOut)
async def mark_delivered(
    order_id: uuid.UUID,
    body: DeliveredIn,
    actor: CanRecord,
    session: SessionDep,
    request: Request,
    background: BackgroundTasks,
) -> OrderOut:
    """Delivering → success (`outcome: accepted`) or return pending (`outcome: returned`, with a
    reason and per item a quantity > 0 and ≤ what was delivered)."""
    order = await _alerting(
        session, request, background, svc.mark_delivered(session, actor, order_id, body)
    )
    return await svc.order_out(session, order)


@router.post("/{order_id}/returns/review", response_model=OrderOut)
async def review_returns(
    order_id: uuid.UUID,
    body: ReviewIn,
    actor: CanReview,
    session: SessionDep,
    request: Request,
    background: BackgroundTasks,
) -> OrderOut:
    """Return pending → partly / fully returned. Per returned item: back to stock + wasted =
    returned, exactly; stock goes back to the batches it came from, newest first."""
    order = await _alerting(
        session, request, background, svc.review_returns(session, actor, order_id, body)
    )
    return await svc.order_out(session, order)
