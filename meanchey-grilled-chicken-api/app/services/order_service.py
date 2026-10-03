"""Orders: boxes of packs and packed by-products, delivery, returns.

```
created ──► delivering ──► success                       (everything accepted)
   │            └────────► return_pending ──► partly_returned | fully_returned
   └──► cancelled                                        (customer cancelled; only while created)
```
No step back. Every write locks the order row (`SELECT … FOR UPDATE`), checks the status
(ORDER_INVALID_STATUS), then the client's `version` (stale → ORDER_CONFLICT with the current
order), then the values, and increments `version`.

Rules enforced here:
- Lines: only orderable items (packs: whole count > 0; packed by-products: kg > 0), one line per
  item per box, at least one box and one line per box. The customer must be active when chosen;
  the driver (optional) an active staff member or supervisor.
- Create / edit only warn about stock (`stock_warnings`). Delivering takes the order's totals out
  of stock, oldest batch first (inventory_service.take_for_order); not enough →
  INVENTORY_INSUFFICIENT and the order stays Created.
- Delivered with returns: a reason, and per item a quantity > 0 and ≤ what was delivered.
- Return review: per returned item, back to stock + wasted = returned, exactly. Stock goes back to
  the batches the order took from, newest first (inventory_service.return_from_order). Fully
  returned when everything delivered came back, otherwise partly returned.
- Delivering, Delivered and the review alert the holders of `orders.review_returns` (stored in the
  same transaction; the router sends them to Telegram after the commit).
"""

import uuid
from collections import Counter
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import Date, case, cast, func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.errors import AppError, ErrorCode
from app.core.phones import format_phone
from app.inventory.catalog import ITEMS_BY_CODE, ORDERABLE, ORDERABLE_CODES, ItemDef
from app.models import (
    Customer,
    Order,
    OrderBox,
    OrderBoxItem,
    OrderCounter,
    OrderReturnItem,
    Role,
    User,
    utcnow,
)
from app.models.order import BOX_COLORS
from app.schemas.common import UserRef
from app.schemas.order import (
    AvailableItem,
    ColorSummary,
    CustomerBrief,
    CustomerOption,
    DeliveredIn,
    DriverOption,
    OrderBoxIn,
    OrderBoxOut,
    OrderCreate,
    OrderLineOut,
    OrderListItem,
    OrderListStatus,
    OrderOut,
    OrderStats,
    OrderSummary,
    OrderUpdate,
    ReturnItemOut,
    ReviewIn,
    StockWarning,
    SummaryItem,
    TotalSummary,
)
from app.services import inventory_service, notification_service
from app.services.audit_service import record
from app.services.inventory_service import Quantities
from app.services.production_service import business_today

ENTITY = "order"
OPTIONS_LIMIT = 20
COMPLETED = ("success", "partly_returned", "fully_returned")
DRIVER_ROLES = (Role.SUPERVISOR, Role.STAFF)
KG_QUANT = Decimal("0.001")
_ORDER = {item.code: i for i, item in enumerate(ORDERABLE)}


# --- Codes and errors ----------------------------------------------------------------------------


async def next_code(session: AsyncSession, day: date) -> str:
    """OR-YYYYMMDD-NNN. The counter row stays locked until the transaction ends, so concurrent
    creations on the same day get distinct numbers."""
    counter = OrderCounter.__table__
    stmt = (
        pg_insert(counter)
        .values(day=day, last_number=1)
        .on_conflict_do_update(
            index_elements=[counter.c.day], set_={"last_number": counter.c.last_number + 1}
        )
        .returning(counter.c.last_number)
    )
    number = (await session.execute(stmt)).scalar_one()
    return f"OR-{day:%Y%m%d}-{number:03d}"


def _field(loc: list[Any], msg: str, type_: str = "value_error") -> dict[str, Any]:
    return {"loc": [str(p) for p in loc], "type": type_, "msg": msg}


def _invalid(fields: list[dict[str, Any]], message: str = "Invalid values") -> AppError:
    return AppError(422, ErrorCode.VALIDATION_ERROR, message, {"fields": fields})


def _wrong_status(order: Order) -> AppError:
    return AppError(
        409,
        ErrorCode.ORDER_INVALID_STATUS,
        "The order is not in a state that allows this",
        {"status": order.status},
    )


def _unit(item: ItemDef) -> str:
    return "count" if item.tracks_count else "kg"


def _q(value: Decimal) -> Decimal:
    return value.quantize(KG_QUANT)


def _split(item: ItemDef, qty: Decimal | None) -> tuple[int | None, Decimal | None]:
    """A quantity in the item's unit → (count, kg)."""
    if qty is None:
        return None, None
    return (int(qty), None) if item.tracks_count else (None, _q(qty))


# --- Loading -------------------------------------------------------------------------------------


async def get_order(session: AsyncSession, order_id: uuid.UUID, *, lock: bool = False) -> Order:
    stmt = select(Order).where(Order.id == order_id).execution_options(populate_existing=True)
    if lock:
        stmt = stmt.with_for_update()
    order = await session.scalar(stmt)
    if order is None:
        raise AppError(404, ErrorCode.ORDER_NOT_FOUND, "Order not found")
    return order


async def _for_write(
    session: AsyncSession, order_id: uuid.UUID, version: int, statuses: tuple[str, ...]
) -> Order:
    order = await get_order(session, order_id, lock=True)
    if order.status not in statuses:
        raise _wrong_status(order)
    if order.version != version:
        current = await order_out(session, order)
        raise AppError(
            409,
            ErrorCode.ORDER_CONFLICT,
            "Someone else changed this order; reload and try again",
            {"order": current.model_dump(mode="json")},
        )
    return order


def _touch(order: Order, actor: User) -> None:
    order.updated_by = actor.id
    order.updated_at = utcnow()
    order.version += 1


def _audit(session: AsyncSession, action: str, actor: User, order: Order, **details: Any) -> None:
    record(
        session,
        action,
        actor_id=actor.id,
        entity_type=ENTITY,
        entity_id=order.id,
        details={"code": order.code, **details},
    )


# --- Validation ----------------------------------------------------------------------------------


async def _customer(session: AsyncSession, customer_id: uuid.UUID) -> Customer:
    customer = await session.get(Customer, customer_id)
    if customer is None:
        raise AppError(422, ErrorCode.CUSTOMER_NOT_FOUND, "Customer not found")
    if not customer.is_active:
        raise AppError(
            422, ErrorCode.CUSTOMER_INACTIVE, "The customer is deactivated; choose another one"
        )
    return customer


async def _driver(session: AsyncSession, driver_id: uuid.UUID) -> User:
    driver = await session.get(User, driver_id)
    if driver is None or not driver.is_active or driver.role not in DRIVER_ROLES:
        # Same answer for every case: it doesn't reveal other accounts.
        raise AppError(
            422,
            ErrorCode.DRIVER_NOT_ALLOWED,
            "The driver must be an active staff member or supervisor",
        )
    return driver


def _validate_boxes(boxes: list[OrderBoxIn]) -> None:
    errors: list[dict[str, Any]] = []
    if not boxes:
        errors.append(_field(["body", "boxes"], "Add at least one box", "too_short"))
    for b, box in enumerate(boxes):
        if not box.lines:
            errors.append(
                _field(["body", "boxes", b, "lines"], "Add at least one item", "too_short")
            )
        seen: set[str] = set()
        for n, line in enumerate(box.lines):
            loc = ["body", "boxes", b, "lines", n]
            item = ITEMS_BY_CODE.get(line.item_code)
            if item is None or line.item_code not in ORDERABLE_CODES:
                errors.append(_field([*loc, "item_code"], "Not an item that can be ordered"))
                continue
            if line.item_code in seen:
                errors.append(_field([*loc, "item_code"], "Already in this box"))
            seen.add(line.item_code)
            errors += _quantity_errors(item, line.count, line.kg, loc)
    if errors:
        raise _invalid(errors)


def _quantity_errors(
    item: ItemDef, count: int | None, kg: Decimal | None, loc: list[Any]
) -> list[dict[str, Any]]:
    """Packs: a whole count > 0 and no kg; by-products: kg > 0 and no count."""
    if item.tracks_count:
        if kg is not None:
            return [_field([*loc, "kg"], "This item is counted, not weighed")]
        if count is None or count <= 0:
            return [_field([*loc, "count"], "Must be greater than 0", "greater_than")]
        return []
    if count is not None:
        return [_field([*loc, "count"], "This item is weighed, not counted")]
    if kg is None or kg <= 0:
        return [_field([*loc, "kg"], "Must be greater than 0", "greater_than")]
    return []


def _build_boxes(boxes: list[OrderBoxIn]) -> list[OrderBox]:
    return [
        OrderBox(
            color=box.color,
            position=b,
            lines=[
                OrderBoxItem(
                    item_code=line.item_code,
                    count=line.count if ITEMS_BY_CODE[line.item_code].tracks_count else None,
                    kg=None if ITEMS_BY_CODE[line.item_code].tracks_count else _q(line.kg or 0),
                    position=n,
                )
                for n, line in enumerate(box.lines, start=1)
            ],
        )
        for b, box in enumerate(boxes, start=1)
    ]


def totals(order: Order) -> Quantities:
    """The order's quantity per item over all boxes, in each item's unit, catalog order."""
    return _totals(order.boxes)


def _totals(boxes: list[OrderBox]) -> Quantities:
    result: dict[str, Decimal] = {}
    for box in boxes:
        for line in box.lines:
            qty = Decimal(line.count) if line.count is not None else Decimal(line.kg or 0)
            result[line.item_code] = result.get(line.item_code, Decimal(0)) + qty
    return dict(sorted(result.items(), key=lambda kv: _ORDER.get(kv[0], 999)))


def _box_counts(order: Order) -> dict[str, int]:
    counts = Counter(box.color for box in order.boxes)
    return {color: counts.get(color, 0) for color in BOX_COLORS}


def _items_payload(quantities: Quantities) -> list[dict[str, Any]]:
    """Items for alerts and audit entries: names kept with them, in the item's unit."""
    out = []
    for code, qty in quantities.items():
        if not qty:
            continue
        item = ITEMS_BY_CODE[code]
        count, kg = _split(item, qty)
        out.append(
            {
                "item_code": code,
                "name_en": item.name_en,
                "name_km": item.name_km,
                "count": count,
                "kg": str(kg) if kg is not None else None,
            }
        )
    return out


def _snapshot(order: Order, customer: Customer | None, driver: User | None) -> dict[str, Any]:
    """What an edit can change, for the audit diff."""
    return {
        "customer": customer.name if customer else None,
        "delivery_date": order.delivery_date.isoformat(),
        "driver": driver.full_name if driver else None,
        "note": order.note,
        "boxes": {
            **_box_counts(order),
            "items": {i["item_code"]: i["count"] or i["kg"] for i in _items_payload(totals(order))},
        },
    }


async def _people(session: AsyncSession, order: Order) -> tuple[Customer | None, User | None]:
    customer = await session.get(Customer, order.customer_id)
    driver = await session.get(User, order.driver_id) if order.driver_id else None
    return customer, driver


# --- Create, edit, cancel ------------------------------------------------------------------------


def _note(value: str | None) -> str | None:
    value = (value or "").strip()
    return value or None


async def create_order(session: AsyncSession, actor: User, data: OrderCreate) -> Order:
    _validate_boxes(data.boxes)
    customer = await _customer(session, data.customer_id)
    if data.driver_id is not None:
        await _driver(session, data.driver_id)
    now = utcnow()
    order = Order(
        code=await next_code(session, business_today(now)),
        customer_id=customer.id,
        delivery_date=data.delivery_date or business_today(now),
        driver_id=data.driver_id,
        note=_note(data.note),
        status="created",
        version=1,
        created_by=actor.id,
        updated_by=actor.id,
        created_at=now,
        updated_at=now,
        boxes=_build_boxes(data.boxes),
        returns=[],
    )
    session.add(order)
    await session.flush()
    _audit(
        session,
        "order.create",
        actor,
        order,
        customer=customer.name,
        delivery_date=order.delivery_date.isoformat(),
        **{f"{c}_boxes": n for c, n in _box_counts(order).items()},
        items=_items_payload(totals(order)),
    )
    await session.commit()
    return await get_order(session, order.id)


async def update_order(
    session: AsyncSession, actor: User, order_id: uuid.UUID, data: OrderUpdate
) -> Order:
    order = await _for_write(session, order_id, data.version, ("created",))
    fields = data.model_fields_set - {"version"}
    if "boxes" in fields:
        _validate_boxes(data.boxes or [])
    errors = [
        _field(["body", f], "Required")
        for f in ("customer_id", "delivery_date", "boxes")
        if f in fields and getattr(data, f) is None
    ]
    if errors:
        raise _invalid(errors)
    before = _snapshot(order, *await _people(session, order))
    if "customer_id" in fields and data.customer_id != order.customer_id:
        assert data.customer_id is not None
        order.customer_id = (await _customer(session, data.customer_id)).id
    if "driver_id" in fields and data.driver_id != order.driver_id:
        if data.driver_id is not None:
            await _driver(session, data.driver_id)
        order.driver_id = data.driver_id
    if "delivery_date" in fields:
        assert data.delivery_date is not None
        order.delivery_date = data.delivery_date
    if "note" in fields:
        order.note = _note(data.note)
    if "boxes" in fields:
        # Delete the old rows first: the new boxes reuse their positions.
        order.boxes.clear()
        await session.flush()
        order.boxes.extend(_build_boxes(data.boxes or []))
    await session.flush()
    after = _snapshot(order, *await _people(session, order))
    changes = {k: {"from": before[k], "to": after[k]} for k in before if before[k] != after[k]}
    if changes:
        _touch(order, actor)
        _audit(session, "order.update", actor, order, changes=changes)
    await session.commit()
    return await get_order(session, order_id)


async def cancel_order(
    session: AsyncSession, actor: User, order_id: uuid.UUID, version: int, reason: str
) -> Order:
    order = await _for_write(session, order_id, version, ("created",))
    now = utcnow()
    order.status = "cancelled"
    order.cancel_reason = reason
    order.cancelled_by = actor.id
    order.cancelled_at = now
    _touch(order, actor)
    _audit(session, "order.cancel", actor, order, reason=reason)
    await session.commit()
    return await get_order(session, order_id)


# --- Delivery and returns ------------------------------------------------------------------------


async def _alert(
    session: AsyncSession, actor: User, order: Order, type_: str, **payload: Any
) -> None:
    customer = await session.get(Customer, order.customer_id)
    await notification_service.notify(
        session,
        type_,
        entity_type=ENTITY,
        entity_id=order.id,
        payload={
            "code": order.code,
            "customer": customer.name if customer else "",
            "actor_id": str(actor.id),
            **payload,
        },
        permission=notification_service.ORDER_ALERT_PERMISSION,
    )


async def start_delivery(
    session: AsyncSession, actor: User, order_id: uuid.UUID, version: int
) -> Order:
    order = await _for_write(session, order_id, version, ("created",))
    quantities = totals(order)
    # Stock out, oldest batch first; INVENTORY_INSUFFICIENT rolls everything back.
    await inventory_service.take_for_order(session, actor, order, quantities)
    order.status = "delivering"
    order.delivering_by = actor.id
    order.delivering_at = utcnow()
    _touch(order, actor)
    _audit(session, "order.delivering", actor, order, items=_items_payload(quantities))
    await _alert(session, actor, order, notification_service.ORDER_DELIVERING, **_box_counts(order))
    await session.commit()
    return await get_order(session, order_id)


async def mark_delivered(
    session: AsyncSession, actor: User, order_id: uuid.UUID, data: DeliveredIn
) -> Order:
    order = await _for_write(session, order_id, data.version, ("delivering",))
    now = utcnow()
    if data.outcome == "accepted":
        if data.items:
            raise _invalid([_field(["body", "items"], "No items when everything was accepted")])
        order.status = "success"
        order.delivered_by = actor.id
        order.delivered_at = now
        _touch(order, actor)
        _audit(session, "order.delivered", actor, order, outcome="accepted")
        await _alert(session, actor, order, notification_service.ORDER_DELIVERED)
        await session.commit()
        return await get_order(session, order_id)

    delivered = totals(order)
    reason = (data.reason or "").strip()
    errors: list[dict[str, Any]] = []
    if not reason:
        errors.append(_field(["body", "reason"], "Reason is required", "missing"))
    if not data.items:
        errors.append(_field(["body", "items"], "Add the returned items", "too_short"))
    returned: Quantities = {}
    for n, line in enumerate(data.items):
        loc = ["body", "items", n]
        item = ITEMS_BY_CODE.get(line.item_code)
        if item is None or line.item_code not in delivered:
            errors.append(_field([*loc, "item_code"], "This item wasn't in the order"))
            continue
        if line.item_code in returned:
            errors.append(_field([*loc, "item_code"], "Listed twice"))
            continue
        problems = _quantity_errors(item, line.count, line.kg, loc)
        if problems:
            errors += problems
            continue
        qty = Decimal(line.count) if item.tracks_count else _q(line.kg or Decimal(0))
        if qty > delivered[line.item_code]:
            field = "count" if item.tracks_count else "kg"
            errors.append(_field([*loc, field], "More than was delivered", "less_than_equal"))
            continue
        returned[line.item_code] = qty
    if errors:
        raise _invalid(errors)

    returned = dict(sorted(returned.items(), key=lambda kv: _ORDER.get(kv[0], 999)))
    for code, qty in returned.items():
        count, kg = _split(ITEMS_BY_CODE[code], qty)
        order.returns.append(OrderReturnItem(item_code=code, returned_count=count, returned_kg=kg))
    order.status = "return_pending"
    order.return_reason = reason
    order.delivered_by = actor.id
    order.delivered_at = now
    _touch(order, actor)
    items = _items_payload(returned)
    _audit(
        session, "order.delivered", actor, order, outcome="returned", reason=reason, returned=items
    )
    await _alert(
        session,
        actor,
        order,
        notification_service.ORDER_RETURN_PENDING,
        returned=items,
        reason=reason,
    )
    await session.commit()
    return await get_order(session, order_id)


async def review_returns(
    session: AsyncSession, actor: User, order_id: uuid.UUID, data: ReviewIn
) -> Order:
    order = await _for_write(session, order_id, data.version, ("return_pending",))
    pending = {r.item_code: r for r in order.returns}
    errors: list[dict[str, Any]] = []
    to_stock: Quantities = {}
    to_wasted: Quantities = {}
    seen: set[str] = set()
    for n, line in enumerate(data.items):
        loc = ["body", "items", n]
        row = pending.get(line.item_code)
        if row is None:
            errors.append(_field([*loc, "item_code"], "This item wasn't returned"))
            continue
        if line.item_code in seen:
            errors.append(_field([*loc, "item_code"], "Listed twice"))
            continue
        seen.add(line.item_code)
        item = ITEMS_BY_CODE[line.item_code]
        if item.tracks_count:
            wrong = [f for f in ("to_stock_kg", "to_wasted_kg") if getattr(line, f) is not None]
            stock, wasted = Decimal(line.to_stock_count or 0), Decimal(line.to_wasted_count or 0)
            returned = Decimal(row.returned_count or 0)
        else:
            wrong = [
                f for f in ("to_stock_count", "to_wasted_count") if getattr(line, f) is not None
            ]
            stock, wasted = _q(line.to_stock_kg or Decimal(0)), _q(line.to_wasted_kg or Decimal(0))
            returned = row.returned_kg or Decimal(0)
        if wrong:
            errors += [_field([*loc, f], "Wrong unit for this item") for f in wrong]
            continue
        if stock + wasted != returned:
            errors.append(
                _field(loc, "Back to stock and wasted must add up to what came back", "sum")
            )
            continue
        to_stock[line.item_code] = stock
        to_wasted[line.item_code] = wasted
    for code in pending:
        if code not in seen:
            errors.append(_field(["body", "items"], f"Missing {code}", "missing"))
    if errors:
        raise _invalid(errors)

    await inventory_service.return_from_order(session, actor, order, to_stock, to_wasted)
    now = utcnow()
    for code, row in pending.items():
        item = ITEMS_BY_CODE[code]
        row.to_stock_count, row.to_stock_kg = _split(item, to_stock[code])
        row.to_wasted_count, row.to_wasted_kg = _split(item, to_wasted[code])
        row.reviewed_by = actor.id
        row.reviewed_at = now
    delivered = totals(order)
    returned_all = {
        code: Decimal(r.returned_count) if r.returned_count is not None else r.returned_kg
        for code, r in pending.items()
    }
    fully = all(returned_all.get(code, Decimal(0)) >= qty for code, qty in delivered.items())
    order.status = "fully_returned" if fully else "partly_returned"
    order.returns_reviewed_by = actor.id
    order.returns_reviewed_at = now
    _touch(order, actor)
    stock_items, wasted_items = _items_payload(to_stock), _items_payload(to_wasted)
    _audit(
        session,
        "order.returns_reviewed",
        actor,
        order,
        outcome=order.status,
        to_stock=stock_items,
        to_wasted=wasted_items,
    )
    await _alert(
        session,
        actor,
        order,
        notification_service.ORDER_RETURNS_REVIEWED,
        outcome=order.status,
        to_stock=stock_items,
        to_wasted=wasted_items,
    )
    await session.commit()
    return await get_order(session, order_id)


# --- Reading -------------------------------------------------------------------------------------


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _box_count(color: str):
    return (
        select(func.count(OrderBox.id))
        .where(OrderBox.order_id == Order.id, OrderBox.color == color)
        .correlate(Order)
        .scalar_subquery()
    )


async def list_orders(
    session: AsyncSession,
    *,
    status: OrderListStatus,
    customer_id: uuid.UUID | None,
    driver_id: uuid.UUID | None,
    date_from: date | None,
    date_to: date | None,
    q: str | None,
    page: int,
    page_size: int,
) -> tuple[list[OrderListItem], int]:
    conditions: list[Any] = []
    if status == "completed":
        conditions.append(Order.status.in_(COMPLETED))
    elif status != "all":
        conditions.append(Order.status == status)
    if customer_id:
        conditions.append(Order.customer_id == customer_id)
    if driver_id:
        conditions.append(Order.driver_id == driver_id)
    if date_from:
        conditions.append(Order.delivery_date >= date_from)
    if date_to:
        conditions.append(Order.delivery_date <= date_to)
    if q and q.strip():
        pattern = f"%{_escape_like(q.strip())}%"
        conditions.append(
            or_(
                Order.code.ilike(pattern, escape="\\"),
                Customer.name.ilike(pattern, escape="\\"),
            )
        )
    base = select(Order).join(Customer, Customer.id == Order.customer_id).where(*conditions)
    total = await session.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = (
        await session.execute(
            base.add_columns(_box_count("white"), _box_count("black"))
            .order_by(Order.delivery_date.desc(), Order.code.desc(), Order.id)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    orders = [r[0] for r in rows]
    customers = await _customers(session, {o.customer_id for o in orders})
    users = await _users(session, {o.driver_id for o in orders if o.driver_id})
    items = [
        OrderListItem(
            id=o.id,
            code=o.code,
            status=o.status,  # type: ignore[arg-type]
            customer=_customer_brief(customers[o.customer_id]),
            delivery_date=o.delivery_date,
            driver=_ref(users, o.driver_id),
            white_boxes=white or 0,
            black_boxes=black or 0,
            created_at=o.created_at,
            updated_at=o.updated_at,
        )
        for o, white, black in rows
    ]
    return items, total


async def stats(session: AsyncSession) -> OrderStats:
    today = business_today()
    month_start = today.replace(day=1)
    next_month = (month_start + timedelta(days=32)).replace(day=1)
    tz = get_settings().business_timezone
    delivered_day = cast(func.timezone(tz, Order.delivered_at), Date)
    row = (
        await session.execute(
            select(
                func.count(case((Order.status == "created", 1))),
                func.count(case((Order.status == "delivering", 1))),
                func.count(case((Order.status == "return_pending", 1))),
                func.count(
                    case(
                        (
                            (Order.delivered_at.is_not(None))
                            & (delivered_day >= month_start)
                            & (delivered_day < next_month),
                            1,
                        )
                    )
                ),
            )
        )
    ).one()
    return OrderStats(
        created=row[0], delivering=row[1], return_pending=row[2], delivered_this_month=row[3]
    )


async def customer_options(session: AsyncSession, q: str | None) -> list[CustomerOption]:
    conditions: list[Any] = [Customer.is_active]
    if q and q.strip():
        term = q.strip()
        matches = [Customer.name.ilike(f"%{_escape_like(term)}%", escape="\\")]
        digits = "".join(ch for ch in term if ch.isdigit())
        if digits:
            matches.append(Customer.phone.contains(digits, autoescape=True))
        conditions.append(or_(*matches))
    rows = await session.scalars(
        select(Customer)
        .where(*conditions)
        .order_by(func.lower(Customer.name), Customer.id)
        .limit(OPTIONS_LIMIT)
    )
    return [CustomerOption(id=c.id, name=c.name, phone_display=format_phone(c.phone)) for c in rows]


async def driver_options(session: AsyncSession) -> list[DriverOption]:
    rows = await session.scalars(
        select(User)
        .where(User.is_active, User.role.in_(DRIVER_ROLES))
        .order_by(func.lower(User.full_name), User.id)
    )
    return [DriverOption(id=u.id, full_name=u.full_name, role=u.role.value) for u in rows]  # type: ignore[arg-type]


async def available_stock(session: AsyncSession) -> list[AvailableItem]:
    codes = [i.code for i in ORDERABLE]
    balances = await inventory_service.available(session, codes)
    out = []
    for item in ORDERABLE:
        count, kg = _split(item, balances[item.code])
        out.append(
            AvailableItem(
                item_code=item.code,
                name_en=item.name_en,
                name_km=item.name_km,
                unit=_unit(item),  # type: ignore[arg-type]
                count=count,
                kg=kg,
            )
        )
    return out


# --- Serialization -------------------------------------------------------------------------------


async def _users(session: AsyncSession, ids: set[uuid.UUID]) -> dict[uuid.UUID, User]:
    if not ids:
        return {}
    return {u.id: u for u in await session.scalars(select(User).where(User.id.in_(ids)))}


async def _customers(session: AsyncSession, ids: set[uuid.UUID]) -> dict[uuid.UUID, Customer]:
    if not ids:
        return {}
    return {c.id: c for c in await session.scalars(select(Customer).where(Customer.id.in_(ids)))}


def _ref(users: dict[uuid.UUID, User], user_id: uuid.UUID | None) -> UserRef | None:
    user = users.get(user_id) if user_id else None
    return UserRef.model_validate(user) if user else None


def _customer_brief(c: Customer) -> CustomerBrief:
    return CustomerBrief(
        id=c.id,
        name=c.name,
        phone_display=format_phone(c.phone),
        location=c.location,
        is_active=c.is_active,
    )


def _summary_items(quantities: Quantities) -> list[SummaryItem]:
    out = []
    for code, qty in quantities.items():
        item = ITEMS_BY_CODE[code]
        count, kg = _split(item, qty)
        out.append(
            SummaryItem(
                item_code=code,
                name_en=item.name_en,
                name_km=item.name_km,
                unit=_unit(item),  # type: ignore[arg-type]
                count=count,
                kg=kg,
            )
        )
    return out


def summary(order: Order) -> OrderSummary:
    colors = []
    for color in BOX_COLORS:
        boxes = [b for b in order.boxes if b.color == color]
        if not boxes:
            continue
        colors.append(
            ColorSummary(
                color=color,  # type: ignore[arg-type]
                boxes=len(boxes),
                items=_summary_items(_totals(boxes)),
            )
        )
    return OrderSummary(
        colors=colors,
        total=TotalSummary(boxes=len(order.boxes), items=_summary_items(totals(order))),
    )


async def stock_warnings(session: AsyncSession, order: Order) -> list[StockWarning]:
    needed = totals(order)
    have = await inventory_service.available(session, list(needed))
    out = []
    for code, qty in needed.items():
        if have[code] >= qty:
            continue
        item = ITEMS_BY_CODE[code]
        a_count, a_kg = _split(item, have[code])
        n_count, n_kg = _split(item, qty)
        out.append(
            StockWarning(
                item_code=code,
                name_en=item.name_en,
                name_km=item.name_km,
                unit=_unit(item),  # type: ignore[arg-type]
                available_count=a_count,
                available_kg=a_kg,
                needed_count=n_count,
                needed_kg=n_kg,
            )
        )
    return out


def _user_ids(order: Order) -> set[uuid.UUID]:
    ids = {
        order.driver_id,
        order.created_by,
        order.updated_by,
        order.delivering_by,
        order.delivered_by,
        order.returns_reviewed_by,
        order.cancelled_by,
        *(r.reviewed_by for r in order.returns),
    }
    return {i for i in ids if i is not None}


async def order_out(session: AsyncSession, order: Order) -> OrderOut:
    users = await _users(session, _user_ids(order))
    customer = await session.get(Customer, order.customer_id)
    assert customer is not None
    delivered = totals(order)
    returns = []
    for r in sorted(order.returns, key=lambda r: _ORDER.get(r.item_code, 999)):
        item = ITEMS_BY_CODE.get(r.item_code)
        if item is None:
            continue
        d_count, d_kg = _split(item, delivered.get(r.item_code, Decimal(0)))
        returns.append(
            ReturnItemOut(
                item_code=r.item_code,
                name_en=item.name_en,
                name_km=item.name_km,
                unit=_unit(item),  # type: ignore[arg-type]
                delivered_count=d_count,
                delivered_kg=d_kg,
                returned_count=r.returned_count,
                returned_kg=r.returned_kg,
                to_stock_count=r.to_stock_count,
                to_stock_kg=r.to_stock_kg,
                to_wasted_count=r.to_wasted_count,
                to_wasted_kg=r.to_wasted_kg,
                reviewed_by=_ref(users, r.reviewed_by),
                reviewed_at=r.reviewed_at,
            )
        )
    return OrderOut(
        id=order.id,
        code=order.code,
        status=order.status,  # type: ignore[arg-type]
        customer=_customer_brief(customer),
        delivery_date=order.delivery_date,
        driver=_ref(users, order.driver_id),
        note=order.note,
        return_reason=order.return_reason,
        cancel_reason=order.cancel_reason,
        version=order.version,
        print_count=order.print_count,
        created_by=_ref(users, order.created_by),
        created_at=order.created_at,
        updated_by=_ref(users, order.updated_by),
        updated_at=order.updated_at,
        delivering_by=_ref(users, order.delivering_by),
        delivering_at=order.delivering_at,
        delivered_by=_ref(users, order.delivered_by),
        delivered_at=order.delivered_at,
        returns_reviewed_by=_ref(users, order.returns_reviewed_by),
        returns_reviewed_at=order.returns_reviewed_at,
        cancelled_by=_ref(users, order.cancelled_by),
        cancelled_at=order.cancelled_at,
        boxes=[
            OrderBoxOut(
                id=box.id,
                color=box.color,  # type: ignore[arg-type]
                position=box.position,
                lines=[
                    OrderLineOut(
                        item_code=line.item_code,
                        name_en=_names(line.item_code)[0],
                        name_km=_names(line.item_code)[1],
                        unit="kg" if line.kg is not None else "count",
                        count=line.count,
                        kg=line.kg,
                    )
                    for line in box.lines
                ],
            )
            for box in order.boxes
        ],
        summary=summary(order),
        returns=returns,
        stock_warnings=await stock_warnings(session, order) if order.status == "created" else [],
    )


def _names(code: str) -> tuple[str, str]:
    item = ITEMS_BY_CODE.get(code)
    return (item.name_en, item.name_km) if item else (code, code)
