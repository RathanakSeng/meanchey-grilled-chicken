"""Inventory: a ledger of movements plus a balance per item, never below zero.

Everything that changes stock goes through `apply_movements` in the caller's transaction:
production (finish / reopen / cancel, `production_service`) and adjustments (`set_value`). It
locks the affected balance rows `FOR UPDATE` in `item_code` order (a fixed order, so two
transactions can't deadlock on them; the batch row, when there is one, is always locked first),
applies the deltas, refuses with `409 INVENTORY_INSUFFICIENT` if any balance would go below zero
(the caller's whole action is then rolled back), and inserts the movements with the balances
after. It never commits.

Every catalog item today has `origin = production`: it changes only through production, and
`set_value` refuses it for everyone (INVENTORY_ITEM_PRODUCTION_ONLY). Adjustments remain for
future `manual` items. Migration 0011 removed the adjustments made before this rule.

Production rules (tracked batches only, `production_batches.inventory_tracked`):
- Finish step 1/2/3 writes the movements of `step_deltas`.
- Reopen reverses the un-reversed movements of the steps sent back to draft, latest step first;
  cancel reverses every un-reversed movement of the batch. A reversal is a new movement with
  `reversal_of` set (unique: a movement is reversed at most once) and `reason` "reopen" / "cancel".
"""

import uuid
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import Select, and_, case, exists, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.config import get_settings
from app.core.errors import AppError, ErrorCode
from app.inventory.catalog import (
    CHICKEN,
    ITEMS,
    ITEMS_BY_CODE,
    PACKS_BIG,
    PACKS_SMALL,
    SECTIONS,
    THIGHS,
    WASTED_THIGHS,
    WASTED_WINGS,
    WINGS,
    ItemDef,
    Section,
    byproduct_packed,
    byproduct_processed,
    wasted_byproduct,
)
from app.models import InventoryBalance, InventoryMovement, ProductionBatch, User, utcnow
from app.permissions.service import effective_permissions
from app.production.catalog import BYPRODUCT_CODES
from app.schemas.common import UserRef
from app.schemas.inventory import (
    InventoryItemDetailOut,
    InventoryItemOut,
    InventoryOut,
    InventorySectionOut,
    ItemSourceOut,
    MovementBatch,
    MovementOut,
    MovementPage,
    MovementSource,
    SetValueIn,
    StockChangeOut,
)
from app.services.audit_service import record

KG_QUANT = Decimal("0.001")
MOVEMENTS_PAGE_SIZE = 50


@dataclass
class Delta:
    """One movement to write. `count` / `kg` are signed; None for a unit the item doesn't track."""

    item_code: str
    count: int | None = None
    kg: Decimal | None = None
    kg_estimated: bool = False
    step: int | None = None
    reversal_of: int | None = None
    reason: str | None = None


def _kg(value: Decimal | None) -> Decimal:
    return (value or Decimal(0)).quantize(KG_QUANT, rounding=ROUND_HALF_UP)


def _item(code: str) -> ItemDef:
    item = ITEMS_BY_CODE.get(code)
    if item is None:
        raise AppError(404, ErrorCode.INVENTORY_ITEM_NOT_FOUND, "Unknown inventory item")
    return item


def _blank(item: ItemDef) -> dict[str, Any]:
    return {
        "item_code": item.code,
        "count": 0 if item.tracks_count else None,
        "kg": Decimal(0) if item.tracks_kg else None,
    }


async def ensure_balances(session: AsyncSession, codes: list[str] | None = None) -> None:
    """A zero balance row for every catalog item (or `codes`) that has none. Idempotent."""
    items = ITEMS if codes is None else [ITEMS_BY_CODE[c] for c in codes]
    if not items:
        return
    await session.execute(
        pg_insert(InventoryBalance)
        .values([_blank(i) for i in items])
        .on_conflict_do_nothing(index_elements=[InventoryBalance.item_code])
    )


def _normalized(delta: Delta) -> Delta | None:
    """Keep only tracked units (a unit not given stays None); None when nothing changes."""
    item = ITEMS_BY_CODE[delta.item_code]
    count = delta.count if item.tracks_count else None
    kg = _kg(delta.kg) if item.tracks_kg and delta.kg is not None else None
    if not count and not kg:
        return None
    delta.count, delta.kg = count, kg
    return delta


async def apply_movements(
    session: AsyncSession,
    actor: User | None,
    deltas: list[Delta],
    *,
    source: MovementSource,
    batch_id: uuid.UUID | None = None,
) -> list[InventoryMovement]:
    """Lock, check, apply and record. Raises INVENTORY_INSUFFICIENT; never commits."""
    rows = [d for d in (_normalized(d) for d in deltas) if d is not None]
    if not rows:
        return []
    codes = sorted({d.item_code for d in rows})
    await ensure_balances(session, codes)
    balances = {
        b.item_code: b
        for b in await session.scalars(
            select(InventoryBalance)
            .where(InventoryBalance.item_code.in_(codes))
            .order_by(InventoryBalance.item_code)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    }

    # Net change per item: refuse before writing anything if one would go below zero.
    net: dict[str, tuple[int, Decimal]] = {}
    for d in rows:
        c, k = net.get(d.item_code, (0, Decimal(0)))
        net[d.item_code] = (c + (d.count or 0), k + (d.kg or Decimal(0)))
    short = []
    for code in codes:
        bal, (dc, dk) = balances[code], net[code]
        count_short = bal.count is not None and bal.count + dc < 0
        kg_short = bal.kg is not None and bal.kg + dk < 0
        if count_short or kg_short:
            short.append(
                {
                    "item_code": code,
                    # Names included: whoever records production may not see the inventory.
                    "name_en": _names(code)[0],
                    "name_km": _names(code)[1],
                    "available_count": bal.count,
                    "available_kg": str(bal.kg) if bal.kg is not None else None,
                    "needed_count": -dc if bal.count is not None and dc < 0 else None,
                    "needed_kg": str(-dk) if bal.kg is not None and dk < 0 else None,
                }
            )
    if short:
        raise AppError(
            409,
            ErrorCode.INVENTORY_INSUFFICIENT,
            "Not enough stock for this change",
            {"items": short},
        )

    now = utcnow()
    written = []
    for d in rows:
        bal = balances[d.item_code]
        if d.count is not None:
            bal.count = (bal.count or 0) + d.count
        if d.kg is not None:
            bal.kg = (bal.kg or Decimal(0)) + d.kg
        bal.updated_at = now
        movement = InventoryMovement(
            item_code=d.item_code,
            count_delta=d.count,
            kg_delta=d.kg,
            kg_estimated=d.kg_estimated,
            source=source,
            batch_id=batch_id,
            step=d.step,
            reversal_of=d.reversal_of,
            reason=d.reason,
            balance_count_after=bal.count,
            balance_kg_after=bal.kg,
            created_by=actor.id if actor else None,
            created_at=now,
        )
        session.add(movement)
        written.append(movement)
    await session.flush()
    return written


# --- Production ----------------------------------------------------------------------------------


def _estimated_kg(rejected: int, kg: Decimal | None, count: int) -> Decimal:
    """Rejected pieces x the batch's average piece weight (step 2 kg / step 2 count)."""
    if not rejected or not count or not kg:
        return Decimal(0)
    return _kg(Decimal(rejected) * kg / Decimal(count))


def step_deltas(batch: ProductionBatch, step: int) -> list[Delta]:
    """The movements of finishing `step`, from the batch's own values."""
    raw, output, packaging = batch.raw_material, batch.output, batch.packaging
    byproducts = {b.item_code: b for b in batch.byproducts}
    if step == 1:
        return [Delta(CHICKEN, raw.quantity, raw.weight_kg, step=1)]
    assert output is not None
    if step == 2:
        deltas = [
            Delta(CHICKEN, -(raw.quantity or 0), -_kg(raw.weight_kg), step=2),
            Delta(WINGS, output.wings_count, output.wings_kg, step=2),
            Delta(THIGHS, output.thighs_count, output.thighs_kg, step=2),
        ]
        for code in BYPRODUCT_CODES:
            row = byproducts.get(code)
            if row is not None:
                deltas.append(Delta(byproduct_processed(code), kg=row.produced_kg, step=2))
        return deltas
    assert packaging is not None
    rejected_wings = packaging.rejected_wings or 0
    rejected_thighs = packaging.rejected_thighs or 0
    deltas = [
        Delta(WINGS, -output.wings_count, -_kg(output.wings_kg), step=3),
        Delta(THIGHS, -output.thighs_count, -_kg(output.thighs_kg), step=3),
        Delta(PACKS_BIG, packaging.big_packages, step=3),
        Delta(PACKS_SMALL, packaging.small_packages, step=3),
        Delta(
            WASTED_WINGS,
            rejected_wings,
            _estimated_kg(rejected_wings, output.wings_kg, output.wings_count),
            kg_estimated=True,
            step=3,
        ),
        Delta(
            WASTED_THIGHS,
            rejected_thighs,
            _estimated_kg(rejected_thighs, output.thighs_kg, output.thighs_count),
            kg_estimated=True,
            step=3,
        ),
    ]
    for code in BYPRODUCT_CODES:
        row = byproducts.get(code)
        if row is None:
            continue
        carry, rejected = _kg(row.carry_kg), _kg(row.rejected_kg)
        # Only what step 3 assigned leaves the processed stock; a remainder stays there.
        deltas += [
            Delta(byproduct_processed(code), kg=-(carry + rejected), step=3),
            Delta(byproduct_packed(code), kg=carry, step=3),
            Delta(wasted_byproduct(code), kg=rejected, step=3),
        ]
    return deltas


async def finish_step(
    session: AsyncSession, actor: User, batch: ProductionBatch, step: int
) -> None:
    if batch.inventory_tracked:
        await apply_movements(
            session, actor, step_deltas(batch, step), source="production", batch_id=batch.id
        )


def _open_movements(batch_id: uuid.UUID) -> Select[tuple[InventoryMovement]]:
    """Original (non-reversal) production movements of a batch not reversed yet."""
    reversal = aliased(InventoryMovement)
    return select(InventoryMovement).where(
        InventoryMovement.batch_id == batch_id,
        InventoryMovement.source == "production",
        InventoryMovement.reversal_of.is_(None),
        ~exists().where(reversal.reversal_of == InventoryMovement.id),
    )


async def reverse(
    session: AsyncSession,
    actor: User,
    batch: ProductionBatch,
    steps: list[int] | None,
    cause: str,
) -> None:
    """Undo the open movements of `steps` (None: every step), latest step first."""
    if not batch.inventory_tracked:
        return
    stmt = _open_movements(batch.id)
    if steps is not None:
        stmt = stmt.where(InventoryMovement.step.in_(steps))
    originals = list(
        await session.scalars(
            stmt.order_by(InventoryMovement.step.desc(), InventoryMovement.id.desc())
        )
    )
    deltas = [
        Delta(
            m.item_code,
            -m.count_delta if m.count_delta is not None else None,
            -m.kg_delta if m.kg_delta is not None else None,
            kg_estimated=m.kg_estimated,
            step=m.step,
            reversal_of=m.id,
            reason=cause,
        )
        for m in originals
    ]
    await apply_movements(session, actor, deltas, source="production", batch_id=batch.id)


async def stock_changes(session: AsyncSession, batch: ProductionBatch) -> list[StockChangeOut]:
    """Net effect of the batch's finished steps (reversed movements left out)."""
    if not batch.inventory_tracked:
        return []
    order = {i.code: i.order for i in ITEMS}
    rows = sorted(
        await session.scalars(_open_movements(batch.id)),
        key=lambda m: (m.step or 0, order.get(m.item_code, 999), m.id),
    )
    return [
        StockChangeOut(
            step=m.step or 0,
            item_code=m.item_code,
            section=_section(m.item_code),
            name_en=_names(m.item_code)[0],
            name_km=_names(m.item_code)[1],
            count_delta=m.count_delta,
            kg_delta=m.kg_delta,
            kg_estimated=m.kg_estimated,
        )
        for m in rows
    ]


# --- Adjustments ---------------------------------------------------------------------------------


def _field_error(loc: list[str], msg: str) -> dict[str, Any]:
    return {"loc": loc, "type": "value_error", "msg": msg}


async def set_value(session: AsyncSession, actor: User, item_code: str, data: SetValueIn) -> None:
    """Set an item's balance to the given value(s): one adjustment movement of the difference.

    Only for `manual` items, with inventory.adjust (no item is manual today). Production items
    change only through production: refused for everyone, the superadmin included.
    """
    item = _item(item_code)
    if item.origin == "production":
        raise AppError(
            409,
            ErrorCode.INVENTORY_ITEM_PRODUCTION_ONLY,
            "This item changes only through production",
            {"item_code": item.code},
        )
    if "inventory.adjust" not in await effective_permissions(session, actor):
        raise AppError(
            403,
            ErrorCode.MISSING_PERMISSION,
            "Missing permission",
            {"required": ["inventory.adjust"]},
        )
    errors = []
    if data.count is None and data.kg is None:
        errors.append(_field_error(["body"], "Give a count or a kg value"))
    if data.count is not None and not item.tracks_count:
        errors.append(_field_error(["body", "count"], "This item has no count"))
    if data.kg is not None and not item.tracks_kg:
        errors.append(_field_error(["body", "kg"], "This item has no weight"))
    if errors:
        raise AppError(422, ErrorCode.VALIDATION_ERROR, "Invalid values", {"fields": errors})

    await ensure_balances(session, [item.code])
    bal = await session.scalar(
        select(InventoryBalance)
        .where(InventoryBalance.item_code == item.code)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    assert bal is not None
    before = {"count": bal.count, "kg": str(bal.kg) if bal.kg is not None else None}
    delta = Delta(
        item.code,
        (data.count - (bal.count or 0)) if data.count is not None else None,
        (_kg(data.kg) - (bal.kg or Decimal(0))) if data.kg is not None else None,
        reason=data.reason,
    )
    written = await apply_movements(session, actor, [delta], source="adjustment")
    if not written:
        return  # already at that value
    after = {"count": bal.count, "kg": str(bal.kg) if bal.kg is not None else None}
    record(
        session,
        "inventory.adjust",
        actor_id=actor.id,
        details={
            "item_code": item.code,
            # Names kept with the entry: the audit log shows them even if the catalog changes.
            "name_en": item.name_en,
            "name_km": item.name_km,
            "from": before,
            "to": after,
            "reason": data.reason,
        },
    )


# --- Reading -------------------------------------------------------------------------------------


def _section(code: str) -> Section | None:
    item = ITEMS_BY_CODE.get(code)
    return item.section if item else None


def _names(code: str) -> tuple[str, str]:
    item = ITEMS_BY_CODE.get(code)
    # An item removed from the catalog keeps its history under its code.
    return (item.name_en, item.name_km) if item else (code, code)


def _item_out(item: ItemDef, bal: InventoryBalance | None, last_change: datetime | None):
    return InventoryItemOut(
        code=item.code,
        section=item.section,
        group=item.group,
        name_en=item.name_en,
        name_km=item.name_km,
        tracks_count=item.tracks_count,
        tracks_kg=item.tracks_kg,
        kg_estimated=item.kg_estimated,
        origin=item.origin,
        count=(bal.count if bal else 0) if item.tracks_count else None,
        kg=(bal.kg if bal else Decimal(0)) if item.tracks_kg else None,
        # None: never changed.
        updated_at=last_change,
    )


async def item_detail(session: AsyncSession, item_code: str) -> InventoryItemDetailOut:
    """One item with its balance and, per batch, what it currently contributes.

    A batch's contribution is the sum of all its movements for the item (reversals included), so
    the contributions add up to the balance while stock only changes through production. Stock
    going out (sales, delivery) will need an allocation rule (e.g. oldest batch first) to keep
    this true.
    """
    item = _item(item_code)
    bal = await session.get(InventoryBalance, item.code)
    last = await session.scalar(
        select(func.max(InventoryMovement.created_at)).where(
            InventoryMovement.item_code == item.code
        )
    )
    reversal = aliased(InventoryMovement)
    still_open = and_(
        InventoryMovement.reversal_of.is_(None),
        ~exists().where(reversal.reversal_of == InventoryMovement.id),
    )
    rows = (
        await session.execute(
            select(
                ProductionBatch.id,
                ProductionBatch.code,
                func.coalesce(func.sum(InventoryMovement.count_delta), 0),
                func.coalesce(func.sum(InventoryMovement.kg_delta), 0),
                func.bool_or(and_(still_open, InventoryMovement.kg_estimated)),
                func.max(case((still_open, InventoryMovement.step))),
            )
            .join(ProductionBatch, ProductionBatch.id == InventoryMovement.batch_id)
            .where(
                InventoryMovement.item_code == item.code,
                InventoryMovement.source == "production",
            )
            .group_by(ProductionBatch.id, ProductionBatch.code, ProductionBatch.created_at)
            .order_by(ProductionBatch.created_at, ProductionBatch.code)
        )
    ).all()
    sources = [
        ItemSourceOut(
            batch_id=batch_id,
            code=code,
            count=int(count) if item.tracks_count else None,
            kg=Decimal(kg) if item.tracks_kg else None,
            kg_estimated=bool(estimated),
            last_step=int(step or 0),
        )
        for batch_id, code, count, kg, estimated, step in rows
        if (item.tracks_count and count) or (item.tracks_kg and kg)
    ]
    return InventoryItemDetailOut(**_item_out(item, bal, last).model_dump(), sources=sources)


async def overview(session: AsyncSession) -> InventoryOut:
    balances = {b.item_code: b for b in await session.scalars(select(InventoryBalance))}
    # Last change = the latest movement (a balance row alone may just have been created).
    last = {
        code: at
        for code, at in await session.execute(
            select(InventoryMovement.item_code, func.max(InventoryMovement.created_at)).group_by(
                InventoryMovement.item_code
            )
        )
    }
    sections = []
    for section in SECTIONS:
        items = []
        for item in (i for i in ITEMS if i.section == section):
            bal = balances.get(item.code)
            items.append(_item_out(item, bal, last.get(item.code)))
        sections.append(InventorySectionOut(section=section, items=items))
    return InventoryOut(sections=sections)


def _day_start(day: date) -> datetime:
    """Midnight of `day` in BUSINESS_TIMEZONE: date filters use business days."""
    return datetime.combine(day, time(), tzinfo=get_settings().business_tz)


async def movements(
    session: AsyncSession,
    *,
    item_code: str | None = None,
    section: Section | None = None,
    source: MovementSource | None = None,
    batch_id: uuid.UUID | None = None,
    batch_code: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    page: int = 1,
    page_size: int = MOVEMENTS_PAGE_SIZE,
) -> MovementPage:
    conditions = []
    if item_code:
        conditions.append(InventoryMovement.item_code == item_code)
    if section:
        conditions.append(
            InventoryMovement.item_code.in_([i.code for i in ITEMS if i.section == section])
        )
    if source:
        conditions.append(InventoryMovement.source == source)
    if batch_id:
        conditions.append(InventoryMovement.batch_id == batch_id)
    if batch_code:
        conditions.append(
            InventoryMovement.batch_id.in_(
                select(ProductionBatch.id).where(
                    ProductionBatch.code.ilike(f"%{_escape_like(batch_code.strip())}%", escape="\\")
                )
            )
        )
    if date_from:
        conditions.append(InventoryMovement.created_at >= _day_start(date_from))
    if date_to:
        conditions.append(InventoryMovement.created_at < _day_start(date_to + timedelta(days=1)))
    where = and_(*conditions) if conditions else None

    count_stmt = select(func.count()).select_from(InventoryMovement)
    list_stmt = select(InventoryMovement)
    if where is not None:
        count_stmt = count_stmt.where(where)
        list_stmt = list_stmt.where(where)
    total = await session.scalar(count_stmt) or 0
    rows = list(
        await session.scalars(
            list_stmt.order_by(InventoryMovement.created_at.desc(), InventoryMovement.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    )

    batch_ids = {m.batch_id for m in rows if m.batch_id}
    codes = (
        {
            b.id: b.code
            for b in await session.execute(
                select(ProductionBatch.id, ProductionBatch.code).where(
                    ProductionBatch.id.in_(batch_ids)
                )
            )
        }
        if batch_ids
        else {}
    )
    user_ids = {m.created_by for m in rows if m.created_by}
    users = (
        {u.id: u for u in await session.scalars(select(User).where(User.id.in_(user_ids)))}
        if user_ids
        else {}
    )
    return MovementPage(
        items=[
            MovementOut(
                id=m.id,
                item_code=m.item_code,
                section=_section(m.item_code),
                name_en=_names(m.item_code)[0],
                name_km=_names(m.item_code)[1],
                count_delta=m.count_delta,
                kg_delta=m.kg_delta,
                kg_estimated=m.kg_estimated,
                source=m.source,  # type: ignore[arg-type]
                batch=MovementBatch(id=m.batch_id, code=codes[m.batch_id])
                if m.batch_id in codes
                else None,
                step=m.step,
                reversal_of=m.reversal_of,
                reason=m.reason,
                balance_count_after=m.balance_count_after,
                balance_kg_after=m.balance_kg_after,
                created_by=UserRef.model_validate(users[m.created_by])
                if m.created_by in users
                else None,
                created_at=m.created_at,
            )
            for m in rows
        ],
        total=total,
        page=page,
        page_size=page_size,
    )


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
