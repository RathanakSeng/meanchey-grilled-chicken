"""Clear stock: chosen quantities of one or more items taken out in one action, with a reason.

Recorded as **CL-YYYYMMDD-NNN** (`inventory_clears` + lines), applied at once, never undone.

- **Where it goes** (`destination`): production items in Processed / Packed move to their wasted
  item (wings, thighs, by-products, packs); everything else (Chicken, materials, prepared items,
  wasted items) is removed.
- **Attribution, oldest first:** production and wasted items are taken from the batches by their
  current net contribution (like an order at Delivering), prepared items from the preparations,
  materials as one movement. What moves to Wasted keeps the batch, so every breakdown still adds
  up to its balance. A counted item that also tracks kg (chicken, wings, thighs, wasted pieces)
  is cleared by count; per batch its kg is the count × the batch's average piece weight (its
  remaining kg ÷ remaining count: step 2's for wings and thighs, the rule production uses for
  wasted pieces), all of it when the whole count goes; that kg is marked estimated.
- **Impacts** (`_impacts`): what the clear leaves short, only for the items cleared: Created
  orders (Delivering would fail), batches waiting at step 2 (their own chicken, the marinade) or
  step 3 (their own wings / thighs / processed by-products, the satay sachets), confirmed plans
  whose step 3 has no sachet counts yet, draft preparations (their inputs), and finished batch
  steps / preparations whose own contribution the clear takes so that they could no longer be
  reopened. They never block the clear, but a clear with impacts needs `acknowledge_impacts`
  (else 409 INVENTORY_CLEAR_UNACKNOWLEDGED with them); the impacts acknowledged are kept on the
  record.

One transaction: the balance rows (cleared items and their wasted items) are locked in item_code
order first, then the contributions and impacts are read, then `apply_movements`
(`source = clear`, `clear_id`). Audit `inventory.clear`; alert (bell + Telegram) to whoever can
open the record: the superadmin and the active holders of `inventory.clear` or
`inventory.history`.
"""

import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import exists, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased, selectinload

from app.core.errors import AppError, ErrorCode
from app.inventory import units
from app.inventory.catalog import (
    CHICKEN,
    ITEMS_BY_CODE,
    PACKS_BIG,
    PACKS_SMALL,
    SATAY_SACHETS,
    THIGHS,
    WASTED_THIGHS,
    WASTED_WINGS,
    WINGS,
    ItemDef,
    byproduct_packed,
    byproduct_processed,
    wasted_byproduct,
    wasted_for,
)
from app.models import (
    InventoryBalance,
    InventoryClear,
    InventoryClearCounter,
    InventoryClearLine,
    InventoryMaterial,
    InventoryMovement,
    Order,
    OrderBox,
    OrderBoxItem,
    Preparation,
    ProductionBatch,
    User,
)
from app.production.catalog import BYPRODUCT_CODES
from app.schemas.common import UserRef
from app.schemas.inventory_clear import (
    ClearCreateIn,
    ClearLineOut,
    ClearOut,
    ClearPage,
    ClearPreviewIn,
    ClearPreviewOut,
    ImpactOut,
    ItemRef,
    PreviewLineOut,
)
from app.services import inventory_service, notification_service
from app.services.audit_service import record
from app.services.inventory_service import Delta, unit_of
from app.services.production_service import business_today

ENTITY = "inventory_clear"
PERMISSION = "inventory.clear"
# Who can open a clear record (GET /inventory/clears/{id}), and so who gets the alert.
READ_PERMISSIONS = ("inventory.clear", "inventory.history")
PAGE_SIZE = 50
_IMPACT_ORDER = {"order": 0, "production": 1, "plan": 2, "preparation": 3, "reopen": 4}

# Production items in Processed / Packed and the wasted item each moves to.
_MOVES_TO: dict[str, str] = {
    WINGS: WASTED_WINGS,
    THIGHS: WASTED_THIGHS,
    PACKS_BIG: wasted_for(PACKS_BIG),
    PACKS_SMALL: wasted_for(PACKS_SMALL),
    **{byproduct_processed(c): wasted_byproduct(c) for c in BYPRODUCT_CODES},
    **{byproduct_packed(c): wasted_byproduct(c) for c in BYPRODUCT_CODES},
}


def destination(code: str) -> str | None:
    """The wasted item a cleared item moves to; None: removed."""
    return _MOVES_TO.get(code)


# --- Amounts -------------------------------------------------------------------------------------

_COLUMNS = {
    "count": InventoryMovement.count_delta,
    "kg": InventoryMovement.kg_delta,
    "g": InventoryMovement.g_delta,
    "m2": InventoryMovement.m2_delta,
}


def _of(bal: InventoryBalance | None, unit: str) -> Decimal:
    if bal is None:
        return Decimal(0)
    return Decimal(getattr(bal, unit) or 0)


def fmt(unit: str, value: Decimal | int) -> str:
    return str(units.quantize(unit, Decimal(value)))  # type: ignore[arg-type]


def _delta(code: str, unit: str, amount: Decimal, **kwargs: Any) -> Delta:
    """A signed movement of `amount` in `unit`."""
    d = Delta(code, **kwargs)
    if unit == "count":
        d.count = int(amount)
    else:
        setattr(d, unit, amount)
    return d


def _is_batch_item(item: ItemDef) -> bool:
    """Production and wasted catalog items: attributed to batches."""
    return item.origin == "production"


def _counted_with_kg(item: ItemDef) -> bool:
    return item.tracks_count and item.tracks_kg


# --- The plan of a clear -------------------------------------------------------------------------


@dataclass
class _Take:
    """What one line takes from one source (a batch, a preparation, or none)."""

    batch_id: uuid.UUID | None
    preparation_id: uuid.UUID | None
    amount: Decimal
    kg: Decimal | None = None
    kg_estimated: bool = False


@dataclass
class _Line:
    item: ItemDef
    unit: str
    quantity: Decimal
    current: Decimal
    takes: list[_Take] = field(default_factory=list)
    destination: ItemDef | None = None

    @property
    def kg(self) -> Decimal | None:
        if not _counted_with_kg(self.item):
            return None
        return sum((t.kg or Decimal(0) for t in self.takes), Decimal(0))

    @property
    def kg_estimated(self) -> bool:
        return any(t.kg_estimated for t in self.takes)


@dataclass
class _Plan:
    lines: list[_Line]
    impacts: list[ImpactOut]

    def deltas(self, clear_id: uuid.UUID) -> list[Delta]:
        out: list[Delta] = []
        for line in self.lines:
            for t in line.takes:
                kwargs = {
                    "batch_id": t.batch_id,
                    "preparation_id": t.preparation_id,
                    "clear_id": clear_id,
                    "kg_estimated": t.kg_estimated,
                }
                d = _delta(line.item.code, line.unit, -t.amount, **kwargs)
                if t.kg is not None:
                    d.kg = -t.kg
                out.append(d)
                if line.destination is not None:
                    moved = _delta(line.destination.code, line.unit, t.amount, **kwargs)
                    if t.kg is not None:
                        moved.kg = t.kg
                        # Wasted pieces' kg is an estimate (the batch's average piece weight).
                        moved.kg_estimated = True
                    out.append(moved)
        return out


def _invalid(fields: list[dict[str, Any]]) -> AppError:
    return AppError(422, ErrorCode.VALIDATION_ERROR, "Invalid values", {"fields": fields})


def _field(loc: list[Any], msg: str, type_: str = "value_error") -> dict[str, Any]:
    return {"loc": [str(p) for p in loc], "type": type_, "msg": msg}


async def _validated(
    session: AsyncSession, data: ClearPreviewIn, *, lock: bool
) -> tuple[list[_Line], dict[str, InventoryBalance]]:
    """Resolve the items, check each quantity (> 0, the unit's precision, ≤ the balance) and read
    (or lock, in item_code order with their wasted items) the balances."""
    codes = [line.item_code for line in data.lines]
    items = await inventory_service.resolve(session, codes)
    unknown = [c for c in codes if c not in items]
    if unknown:
        raise AppError(
            404,
            ErrorCode.INVENTORY_ITEM_NOT_FOUND,
            "Unknown inventory item",
            {"item_codes": unknown},
        )
    dests = {c: destination(c) for c in codes}
    errors = []
    for i, line in enumerate(data.lines):
        unit = unit_of(items[line.item_code])
        loc = ["body", "lines", i, "quantity"]
        if line.quantity <= 0:
            errors.append(_field(loc, "Must be more than 0", "greater_than"))
        elif not units.has_precision(unit, line.quantity):
            errors.append(_field(loc, f"At most {units.DECIMALS[unit]} decimals for {unit}"))
    if errors:
        raise _invalid(errors)
    wanted = sorted({*codes, *(d for d in dests.values() if d)})
    if lock:
        balances = await inventory_service.lock_balances(session, wanted)
    else:
        balances = {
            b.item_code: b
            for b in await session.scalars(
                select(InventoryBalance).where(InventoryBalance.item_code.in_(wanted))
            )
        }
    lines: list[_Line] = []
    short = []
    for line in data.lines:
        item = items[line.item_code]
        unit = unit_of(item)
        bal = balances.get(item.code)
        current = _of(bal, unit)
        if line.quantity > current:
            short.append(
                inventory_service._short_entry(
                    item,
                    bal or InventoryBalance(item_code=item.code, **_zero(item)),
                    int(line.quantity) if unit == "count" else None,
                    line.quantity if unit == "kg" else None,
                    line.quantity if unit == "g" else None,
                    line.quantity if unit == "m2" else None,
                )
            )
            continue
        dest = dests[item.code]
        lines.append(
            _Line(
                item,
                unit,
                units.quantize(unit, line.quantity),  # type: ignore[arg-type]
                current,
                destination=ITEMS_BY_CODE[dest] if dest else None,
            )
        )
    if short:
        raise inventory_service._insufficient(short)
    return lines, balances


def _zero(item: ItemDef) -> dict[str, Any]:
    return {
        "count": 0 if item.tracks_count else None,
        "kg": Decimal(0) if item.tracks_kg else None,
        "g": Decimal(0) if item.tracks_g else None,
        "m2": Decimal(0) if item.tracks_m2 else None,
    }


async def _preparation_contributions(
    session: AsyncSession, code: str, unit: str
) -> list[tuple[uuid.UUID, Decimal]]:
    """Each preparation's current net amount of a prepared item (any unit), oldest first."""
    rows = await session.execute(
        select(InventoryMovement.preparation_id, func.coalesce(func.sum(_COLUMNS[unit]), 0))
        .join(Preparation, Preparation.id == InventoryMovement.preparation_id)
        .where(InventoryMovement.item_code == code)
        .group_by(InventoryMovement.preparation_id, Preparation.code)
        .order_by(func.min(InventoryMovement.created_at), Preparation.code)
    )
    return [(p_id, Decimal(n)) for p_id, n in rows]


def _take_batches(
    line: _Line,
    sources: list[tuple[uuid.UUID, int, Decimal]],
    bal: InventoryBalance | None,
) -> None:
    """Oldest batch first; stock attributed to no batch last."""
    item = line.item
    with_kg = _counted_with_kg(item)
    rows: list[tuple[uuid.UUID | None, Decimal, Decimal]] = [
        (b_id, Decimal(c) if item.tracks_count else k, k) for b_id, c, k in sources
    ]
    rest = _of(bal, line.unit) - sum((n for _, n, _ in rows if n > 0), Decimal(0))
    rest_kg = _of(bal, "kg") - sum((k for _, n, k in rows if n > 0), Decimal(0))
    if rest > 0:
        rows.append((None, rest, rest_kg))
    left = line.quantity
    for b_id, net, net_kg in rows:
        if left <= 0:
            break
        if net <= 0:
            continue
        take = min(net, left)
        left -= take
        kg = None
        estimated = False
        if with_kg:
            if take == net:
                kg = max(net_kg, Decimal(0))
            else:
                # The batch's average piece weight (= step 2's for wings and thighs).
                kg = min(net_kg, inventory_service._kg(take * net_kg / net))
                estimated = True
            estimated = estimated or item.kg_estimated
        line.takes.append(_Take(b_id, None, take, kg, estimated))


def _take_preparations(line: _Line, sources: list[tuple[uuid.UUID, Decimal]]) -> None:
    left = line.quantity
    for p_id, net in sources:
        if left <= 0:
            break
        if net <= 0:
            continue
        take = min(net, left)
        line.takes.append(_Take(None, p_id, take))
        left -= take
    if left > 0:
        line.takes.append(_Take(None, None, left))


async def _plan(session: AsyncSession, data: ClearPreviewIn, *, lock: bool) -> _Plan:
    lines, balances = await _validated(session, data, lock=lock)
    batch_codes = [line.item.code for line in lines if _is_batch_item(line.item)]
    contributions = (
        await inventory_service.batch_contributions(session, batch_codes) if batch_codes else {}
    )
    for line in lines:
        if _is_batch_item(line.item):
            _take_batches(line, contributions[line.item.code], balances.get(line.item.code))
        elif line.item.origin == "preparation":
            sources = await _preparation_contributions(session, line.item.code, line.unit)
            _take_preparations(line, sources)
        else:
            line.takes.append(_Take(None, None, line.quantity))
    impacts = await _impacts(session, lines, contributions)
    return _Plan(lines, impacts)


# --- Impacts -------------------------------------------------------------------------------------


@dataclass
class _After:
    """Stock left once the clear is applied: overall and per batch / preparation."""

    lines: dict[str, _Line]
    batch_before: dict[tuple[str, uuid.UUID], Decimal]
    prep_before: dict[tuple[str, uuid.UUID], Decimal]

    def total(self, code: str) -> Decimal:
        line = self.lines[code]
        return line.current - line.quantity

    def batch(self, code: str, batch_id: uuid.UUID) -> tuple[Decimal, Decimal]:
        """(before, after) of a batch's own contribution."""
        before = self.batch_before.get((code, batch_id), Decimal(0))
        taken = sum(
            (t.amount for t in self.lines[code].takes if t.batch_id == batch_id), Decimal(0)
        )
        return before, before - taken

    def preparation(self, code: str, p_id: uuid.UUID) -> tuple[Decimal, Decimal]:
        before = self.prep_before.get((code, p_id), Decimal(0))
        taken = sum(
            (t.amount for t in self.lines[code].takes if t.preparation_id == p_id), Decimal(0)
        )
        return before, before - taken


def _impact(
    type_: str,
    code: str,
    id_: uuid.UUID,
    line: _Line,
    needed: Decimal,
    after: Decimal,
    key: str,
    step: int | None = None,
) -> ImpactOut:
    return ImpactOut(
        type=type_,  # type: ignore[arg-type]
        code=code,
        id=id_,
        step=step,
        item_code=line.item.code,
        name_en=line.item.name_en,
        name_km=line.item.name_km,
        unit=line.unit,  # type: ignore[arg-type]
        needed=fmt(line.unit, needed),
        available_after=fmt(line.unit, max(after, Decimal(0))),
        message_key=key,  # type: ignore[arg-type]
    )


async def _impacts(
    session: AsyncSession,
    lines: list[_Line],
    contributions: dict[str, list[tuple[uuid.UUID, int, Decimal]]],
) -> list[ImpactOut]:
    by_code = {line.item.code: line for line in lines}
    batch_before = {
        (code, b_id): Decimal(c) if ITEMS_BY_CODE[code].tracks_count else k
        for code, rows in contributions.items()
        for b_id, c, k in rows
    }
    prep_before: dict[tuple[str, uuid.UUID], Decimal] = {}
    for line in lines:
        if line.item.origin == "preparation":
            for p_id, net in await _preparation_contributions(session, line.item.code, line.unit):
                prep_before[(line.item.code, p_id)] = net
    after = _After(by_code, batch_before, prep_before)
    impacts: list[ImpactOut] = []
    impacts += await _order_impacts(session, after)
    production = await _production_impacts(session, after)
    impacts += production
    impacts += await _preparation_impacts(session, after)
    blocked = {(i.id, i.item_code) for i in production}
    impacts += await _reopen_impacts(session, after, blocked)
    return sorted(impacts, key=lambda i: (_IMPACT_ORDER[i.type], i.code, i.item_code))


async def _order_impacts(session: AsyncSession, after: _After) -> list[ImpactOut]:
    """Created orders whose total of a cleared item is more than what is left."""
    rows = await session.execute(
        select(
            Order.id,
            Order.code,
            OrderBoxItem.item_code,
            func.coalesce(func.sum(OrderBoxItem.count), 0),
            func.coalesce(func.sum(OrderBoxItem.kg), 0),
        )
        .join(OrderBox, OrderBox.order_id == Order.id)
        .join(OrderBoxItem, OrderBoxItem.box_id == OrderBox.id)
        .where(Order.status == "created", OrderBoxItem.item_code.in_(list(after.lines)))
        .group_by(Order.id, Order.code, OrderBoxItem.item_code)
    )
    out = []
    for o_id, code, item_code, count, kg in rows:
        line = after.lines[item_code]
        needed = Decimal(count) if line.item.tracks_count else Decimal(kg)
        left = after.total(item_code)
        if needed > left:
            out.append(_impact("order", code, o_id, line, needed, left, "order_short"))
    return out


def _sachets_needed(batch: ProductionBatch) -> dict[int, tuple[str, int]]:
    """Per pack size: ("production", step 3's count) once step 3 has sachet counts, else
    ("plan", the confirmed plan's packs)."""
    packaging, plan = batch.packaging, batch.plan
    out: dict[int, tuple[str, int]] = {}
    for size in (4, 2):
        used = getattr(packaging, f"sachets_{size}_used", None) if packaging else None
        if used is not None:
            out[size] = ("production", used)
        elif plan is not None and plan.status == "confirmed":
            expected = plan.expected_big if size == 4 else plan.expected_small
            out[size] = ("plan", expected or 0)
    return out


async def _production_impacts(session: AsyncSession, after: _After) -> list[ImpactOut]:
    """In-progress tracked batches waiting at step 2 or step 3."""
    codes = set(after.lines)
    marinade = await inventory_service.marinade_material(session)
    batches = list(
        await session.scalars(
            select(ProductionBatch)
            .where(ProductionBatch.status == "in_progress", ProductionBatch.inventory_tracked)
            .options(
                selectinload(ProductionBatch.raw_material),
                selectinload(ProductionBatch.output),
                selectinload(ProductionBatch.packaging),
                selectinload(ProductionBatch.byproducts),
                selectinload(ProductionBatch.plan),
            )
            .order_by(ProductionBatch.created_at, ProductionBatch.code)
        )
    )
    out: list[ImpactOut] = []

    def own(code: str, b: ProductionBatch, needed: Decimal, key: str, step: int) -> None:
        if code not in codes or needed <= 0:
            return
        _, left = after.batch(code, b.id)
        if needed > left:
            out.append(
                _impact("production", b.code, b.id, after.lines[code], needed, left, key, step)
            )

    def shared(code: str, b: ProductionBatch, needed: Decimal, type_: str, key: str, step: int):
        if code not in codes or needed <= 0:
            return
        left = after.total(code)
        if needed > left:
            out.append(_impact(type_, b.code, b.id, after.lines[code], needed, left, key, step))

    for b in batches:
        raw, output, packaging = b.raw_material, b.output, b.packaging
        if raw is None or raw.status != "finished":
            continue
        if output is not None and output.status == "draft":
            key = "production_step2_short"
            own(CHICKEN, b, Decimal(raw.quantity or 0), key, 2)
            if marinade is not None and output.marinade_g:
                grams = Decimal(output.marinade_g)
                need = grams if marinade.unit == "g" else units.convert(grams, "g", "kg")
                shared(marinade.item_code, b, need, "production", key, 2)
            continue
        if output is None or output.status != "finished":
            continue
        if packaging is None or packaging.status != "draft":
            continue
        key = "production_step3_short"
        own(WINGS, b, Decimal(output.wings_count or 0), key, 3)
        own(THIGHS, b, Decimal(output.thighs_count or 0), key, 3)
        for bp in b.byproducts:
            if bp.carry_kg is not None or bp.rejected_kg is not None:
                need = Decimal(bp.carry_kg or 0) + Decimal(bp.rejected_kg or 0)
            else:
                need = Decimal(bp.produced_kg or 0)
            own(byproduct_processed(bp.item_code), b, need, key, 3)
        for size, (kind, n) in _sachets_needed(b).items():
            plan_key = "plan_sachets_short" if kind == "plan" else key
            shared(SATAY_SACHETS[size], b, Decimal(n), kind, plan_key, 3)
    return out


async def _preparation_impacts(session: AsyncSession, after: _After) -> list[ImpactOut]:
    """Draft preparations whose inputs are more than what is left."""
    from app.services.preparation_service import SATAY, SATAY_SAUCE, ZIP_BAG_ROLES, _role_materials

    drafts = list(
        await session.scalars(
            select(Preparation)
            .where(Preparation.status == "draft")
            .options(selectinload(Preparation.lines))
            .order_by(Preparation.created_at, Preparation.code)
        )
    )
    if not drafts:
        return []
    roles = await _role_materials(session)
    material_ids = {line.material_id for p in drafts for line in p.lines if line.material_id}
    materials = (
        {
            m.id: m
            for m in await session.scalars(
                select(InventoryMaterial).where(InventoryMaterial.id.in_(material_ids))
            )
        }
        if material_ids
        else {}
    )
    out = []
    for p in drafts:
        needs: dict[str, Decimal] = defaultdict(Decimal)

        def add(
            needs: dict[str, Decimal],
            m: InventoryMaterial | None,
            qty: Decimal | None,
            unit: str | None,
        ) -> None:
            if m is None or qty is None or qty <= 0 or m.item_code not in after.lines:
                return
            unit = unit or m.unit
            if unit != m.unit:
                if not units.same_measure(unit, m.unit):  # type: ignore[arg-type]
                    return
                qty = units.convert(qty, unit, m.unit)  # type: ignore[arg-type]
            needs[m.item_code] += qty

        for line in p.lines:
            if p.type == SATAY:
                add(needs, roles.get(SATAY_SAUCE), line.satay_g, "g")
                add(needs, roles.get(ZIP_BAG_ROLES[line.pack_size or 2]), line.quantity, line.unit)
            else:
                m = materials.get(line.material_id) if line.material_id else None
                add(needs, m, line.quantity, line.unit)
        for code, need in needs.items():
            left = after.total(code)
            if need > left:
                out.append(
                    _impact(
                        "preparation",
                        p.code,
                        p.id,
                        after.lines[code],
                        need,
                        left,
                        "preparation_short",
                    )
                )
    return out


def _open(stmt_where: list[Any]) -> Any:
    reversal = aliased(InventoryMovement)
    return [
        *stmt_where,
        InventoryMovement.reversal_of.is_(None),
        ~exists().where(reversal.reversal_of == InventoryMovement.id),
    ]


async def _reopen_impacts(
    session: AsyncSession, after: _After, blocked: set[tuple[uuid.UUID, str]]
) -> list[ImpactOut]:
    """Finished batch steps and preparations whose own contribution the clear takes, so that a
    reopen (or cancel) could no longer take back what they made."""
    out: list[ImpactOut] = []
    batch_takes = {
        (line.item.code, t.batch_id)
        for line in after.lines.values()
        for t in line.takes
        if t.batch_id is not None
    }
    batch_ids = {b for _, b in batch_takes}
    if batch_ids:
        rows = await session.execute(
            select(
                InventoryMovement.batch_id,
                InventoryMovement.item_code,
                func.coalesce(func.sum(InventoryMovement.count_delta), 0),
                func.coalesce(func.sum(InventoryMovement.kg_delta), 0),
                func.max(InventoryMovement.step),
                ProductionBatch.code,
            )
            .join(ProductionBatch, ProductionBatch.id == InventoryMovement.batch_id)
            .where(
                *_open(
                    [
                        InventoryMovement.source == "production",
                        InventoryMovement.batch_id.in_(batch_ids),
                        InventoryMovement.item_code.in_(list(after.lines)),
                    ]
                ),
                ProductionBatch.status != "cancelled",
            )
            .group_by(InventoryMovement.batch_id, InventoryMovement.item_code, ProductionBatch.code)
        )
        for b_id, code, count, kg, step, b_code in rows:
            if (code, b_id) not in batch_takes or (b_id, code) in blocked:
                continue
            line = after.lines[code]
            made = Decimal(count) if line.item.tracks_count else Decimal(kg)
            before, left = after.batch(code, b_id)
            if made > 0 and before >= made > left:
                out.append(
                    _impact("reopen", b_code, b_id, line, made, left, "reopen_batch_blocked", step)
                )
    prep_takes = {
        (line.item.code, t.preparation_id)
        for line in after.lines.values()
        for t in line.takes
        if t.preparation_id is not None
    }
    prep_ids = {p for _, p in prep_takes}
    if prep_ids:
        for code in {c for c, _ in prep_takes}:
            line = after.lines[code]
            rows = await session.execute(
                select(
                    InventoryMovement.preparation_id,
                    func.coalesce(func.sum(_COLUMNS[line.unit]), 0),
                    Preparation.code,
                )
                .join(Preparation, Preparation.id == InventoryMovement.preparation_id)
                .where(
                    *_open(
                        [
                            InventoryMovement.source == "preparation",
                            InventoryMovement.preparation_id.in_(prep_ids),
                            InventoryMovement.item_code == code,
                        ]
                    ),
                    Preparation.status == "finished",
                )
                .group_by(InventoryMovement.preparation_id, Preparation.code)
            )
            for p_id, made, p_code in rows:
                if (code, p_id) not in prep_takes:
                    continue
                made = Decimal(made)
                before, left = after.preparation(code, p_id)
                if made > 0 and before >= made > left:
                    out.append(
                        _impact(
                            "reopen", p_code, p_id, line, made, left, "reopen_preparation_blocked"
                        )
                    )
    return out


# --- Preview and create --------------------------------------------------------------------------


def _ref(item: ItemDef | None) -> ItemRef | None:
    if item is None:
        return None
    return ItemRef(
        item_code=item.code, name_en=item.name_en, name_km=item.name_km, section=item.section
    )


async def preview(session: AsyncSession, data: ClearPreviewIn) -> ClearPreviewOut:
    """Per line: current / after, the kg a counted item takes, where it goes; and the impacts.
    Nothing is written."""
    plan = await _plan(session, data, lock=False)
    return ClearPreviewOut(
        lines=[
            PreviewLineOut(
                item_code=line.item.code,
                name_en=line.item.name_en,
                name_km=line.item.name_km,
                section=line.item.section,
                group=line.item.group,
                unit=line.unit,  # type: ignore[arg-type]
                current=fmt(line.unit, line.current),
                clear=fmt(line.unit, line.quantity),
                after=fmt(line.unit, line.current - line.quantity),
                kg=fmt("kg", line.kg) if line.kg is not None else None,
                kg_estimated=line.kg_estimated,
                destination=_ref(line.destination),
            )
            for line in plan.lines
        ],
        impacts=plan.impacts,
    )


async def next_code(session: AsyncSession, day: date) -> str:
    """CL-YYYYMMDD-NNN; the counter row stays locked until the transaction ends."""
    counter = InventoryClearCounter.__table__
    stmt = (
        pg_insert(counter)
        .values(day=day, last_number=1)
        .on_conflict_do_update(
            index_elements=[counter.c.day], set_={"last_number": counter.c.last_number + 1}
        )
        .returning(counter.c.last_number)
    )
    number = (await session.execute(stmt)).scalar_one()
    return f"CL-{day:%Y%m%d}-{number:03d}"


def _impact_counts(impacts: list[ImpactOut]) -> dict[str, int]:
    """How many distinct records of each type are affected."""
    seen: dict[str, set[uuid.UUID]] = defaultdict(set)
    for i in impacts:
        seen[i.type].add(i.id)
    return {t: len(ids) for t, ids in seen.items()}


async def _recipients(session: AsyncSession) -> list[User]:
    """Whoever can open the record: the superadmin and the active holders of inventory.clear or
    inventory.history (`notification_service.recipients`, effective permissions)."""
    users: dict[uuid.UUID, User] = {}
    for permission in READ_PERMISSIONS:
        for u in await notification_service.recipients(session, permission):
            users.setdefault(u.id, u)
    return sorted(users.values(), key=lambda u: (u.created_at, u.id))


async def create(session: AsyncSession, actor: User, data: ClearCreateIn) -> InventoryClear:
    plan = await _plan(session, data, lock=True)
    if plan.impacts and not data.acknowledge_impacts:
        raise AppError(
            409,
            ErrorCode.INVENTORY_CLEAR_UNACKNOWLEDGED,
            "This clear affects orders, production or preparations: acknowledge it first",
            {"impacts": [i.model_dump(mode="json") for i in plan.impacts]},
        )
    clear = InventoryClear(
        id=uuid.uuid4(),
        code=await next_code(session, business_today()),
        reason=data.reason,
        impacts_snapshot=[i.model_dump(mode="json") for i in plan.impacts],
        created_by=actor.id,
    )
    session.add(clear)
    await session.flush()
    await inventory_service.apply_movements(session, actor, plan.deltas(clear.id), source="clear")
    lines_summary = []
    for position, line in enumerate(plan.lines, start=1):
        session.add(
            InventoryClearLine(
                clear_id=clear.id,
                position=position,
                item_code=line.item.code,
                count=int(line.quantity) if line.unit == "count" else None,
                kg=line.quantity if line.unit == "kg" else line.kg,
                g=line.quantity if line.unit == "g" else None,
                m2=line.quantity if line.unit == "m2" else None,
                kg_estimated=line.kg_estimated,
                moved_to_item_code=line.destination.code if line.destination else None,
            )
        )
        lines_summary.append(
            {
                "item_code": line.item.code,
                "name_en": line.item.name_en,
                "name_km": line.item.name_km,
                "quantity": fmt(line.unit, line.quantity),
                "unit": line.unit,
                "kg": fmt("kg", line.kg) if line.kg is not None else None,
                "moved_to": line.destination.code if line.destination else None,
            }
        )
    counts = _impact_counts(plan.impacts)
    record(
        session,
        "inventory.clear",
        actor_id=actor.id,
        entity_type=ENTITY,
        entity_id=clear.id,
        details={
            "code": clear.code,
            "lines": lines_summary,
            "reason": clear.reason,
            "impacts": counts,
        },
    )
    notification_service.notify_users(
        session,
        notification_service.INVENTORY_CLEARED,
        await _recipients(session),
        entity_type=ENTITY,
        entity_id=clear.id,
        payload={
            "code": clear.code,
            "items": [
                {k: v for k, v in s.items() if k in ("name_en", "name_km", "quantity", "unit")}
                for s in lines_summary
            ],
            "reason": clear.reason,
            "impacts": counts,
            "actor_id": str(actor.id),
        },
    )
    await session.commit()
    return await get(session, clear.id)


# --- Reading -------------------------------------------------------------------------------------


async def get(session: AsyncSession, clear_id: uuid.UUID) -> InventoryClear:
    clear = await session.scalar(
        select(InventoryClear)
        .where(InventoryClear.id == clear_id)
        .options(selectinload(InventoryClear.lines))
        .execution_options(populate_existing=True)
    )
    if clear is None:
        raise AppError(404, ErrorCode.INVENTORY_CLEAR_NOT_FOUND, "Clear not found")
    return clear


async def _outs(session: AsyncSession, clears: list[InventoryClear]) -> list[ClearOut]:
    codes = {line.item_code for c in clears for line in c.lines}
    codes |= {
        line.moved_to_item_code for c in clears for line in c.lines if line.moved_to_item_code
    }
    items = await inventory_service.resolve(session, codes)
    user_ids = {c.created_by for c in clears if c.created_by}
    users = (
        {u.id: u for u in await session.scalars(select(User).where(User.id.in_(user_ids)))}
        if user_ids
        else {}
    )

    def line_out(line: InventoryClearLine) -> ClearLineOut:
        item = items.get(line.item_code)
        if line.g is not None:
            unit, qty = "g", line.g
        elif line.m2 is not None:
            unit, qty = "m2", line.m2
        elif line.count is not None:
            unit, qty = "count", Decimal(line.count)
        else:
            unit, qty = "kg", line.kg or Decimal(0)
        return ClearLineOut(
            item_code=line.item_code,
            name_en=item.name_en if item else line.item_code,
            name_km=item.name_km if item else line.item_code,
            section=item.section if item else None,
            unit=unit,  # type: ignore[arg-type]
            quantity=fmt(unit, qty),
            kg=fmt("kg", line.kg) if unit == "count" and line.kg is not None else None,
            kg_estimated=line.kg_estimated,
            moved_to=_ref(items.get(line.moved_to_item_code)) if line.moved_to_item_code else None,
        )

    return [
        ClearOut(
            id=c.id,
            code=c.code,
            reason=c.reason,
            lines=[line_out(line) for line in c.lines],
            impacts=[ImpactOut.model_validate(i) for i in c.impacts_snapshot or []],
            created_by=UserRef.model_validate(users[c.created_by])
            if c.created_by in users
            else None,
            created_at=c.created_at,
        )
        for c in clears
    ]


async def clear_out(session: AsyncSession, clear: InventoryClear) -> ClearOut:
    return (await _outs(session, [clear]))[0]


async def list_clears(
    session: AsyncSession,
    *,
    date_from: date | None = None,
    date_to: date | None = None,
    page: int = 1,
    page_size: int = PAGE_SIZE,
) -> ClearPage:
    """Newest first; dates are business days (BUSINESS_TIMEZONE)."""
    conditions = []
    if date_from:
        conditions.append(InventoryClear.created_at >= inventory_service._day_start(date_from))
    if date_to:
        conditions.append(
            InventoryClear.created_at < inventory_service._day_start(date_to + timedelta(days=1))
        )
    total = await session.scalar(select(func.count(InventoryClear.id)).where(*conditions)) or 0
    rows = list(
        await session.scalars(
            select(InventoryClear)
            .where(*conditions)
            .options(selectinload(InventoryClear.lines))
            .order_by(InventoryClear.created_at.desc(), InventoryClear.code.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    )
    return ClearPage(items=await _outs(session, rows), total=total, page=page, page_size=page_size)
