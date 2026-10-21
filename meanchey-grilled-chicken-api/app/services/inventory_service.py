"""Inventory: a ledger of movements plus a balance per item, never below zero.

Everything that changes stock goes through `apply_movements` in the caller's transaction:
production (finish / reopen / cancel, `production_service`), orders (Delivering and the return
review, `order_service`) and adjustments (`set_value`). It
locks the affected balance rows `FOR UPDATE` in `item_code` order (a fixed order, so two
transactions can't deadlock on them; the batch row, when there is one, is always locked first),
applies the deltas, refuses with `409 INVENTORY_INSUFFICIENT` if any balance would go below zero
(the caller's whole action is then rolled back), and inserts the movements with the balances
after. It never commits.

Every catalog item has `origin = production`: it changes only through production and orders,
and `set_value` refuses it for everyone (INVENTORY_ITEM_PRODUCTION_ONLY). Migration 0011 removed
the adjustments made before this rule.

**Materials** (`inventory_materials`, `origin = manual`, group raw) are items resolved from the
database (`resolve`): their stock changes by hand (`material_service`: add / remove, through
`apply_movements` like everything else) and, for Marinade sauce, by step 2. A material has one
unit: count, kg, g or m2 (grams in the `g` / `g_delta` columns, square metres in `m2` /
`m2_delta`, app/inventory/units.py).

Per-batch attribution: every movement of a production item carries the batch its quantity
belongs to, so a batch's current contribution to an item is the sum of its movements (any
source). Orders keep this exact:
- Delivering (`take_for_order`) splits each item across the batches by their current
  contribution, **oldest batch first** (FIFO), one movement per (item, batch), `source = order`.
- The return review (`return_from_order`) gives back to the batches the order took from,
  **newest first**: first what goes back to stock, then what goes to wasted (the wasted item of
  the same batch), `source = order_return`.
- A production reversal (reopen / cancel, `reverse`) needs the batch's own remaining contribution
  to cover it, otherwise `409 PRODUCTION_STOCK_ALREADY_USED` (its stock already left in orders).
The contributions are read after the balance rows are locked, so a concurrent order or reversal
on the same items waits and then sees the other's movements.

Production rules (tracked batches only, `production_batches.inventory_tracked`):
- Finish step 1/2/3 writes the movements of `step_deltas`; step 2 also takes its `marinade_g`
  out of the Marinade sauce material (converted when that material is in kg), in the same
  transaction: not enough → INVENTORY_INSUFFICIENT and the Finish is refused.
- Step 3 also takes the satay sachets used (`sachets_4_used` / `sachets_2_used`) out of
  `satay_sachet_4` / `satay_sachet_2`, split across the preparations that made them by their
  current net contribution, **oldest preparation first**: one movement per (item, preparation),
  with both `batch_id` and `preparation_id` set, so the item's preparation breakdown still adds
  up to the balance. Not enough → INVENTORY_INSUFFICIENT.
- Reopen reverses the un-reversed movements of the steps sent back to draft, latest step first;
  cancel reverses every un-reversed movement of the batch. A reversal is a new movement with
  `reversal_of` set (unique: a movement is reversed at most once) and `reason` "reopen" / "cancel".
  A material's reversal is written in the material's current unit (it may have switched kg <-> g
  since), and materials are left out of the "stock already used in orders" guard. A reversal
  keeps the original's `preparation_id`: sachets go back to the preparations they came from.

**Prepared items** (section `prepared`, origin `preparation`): the satay sachets (catalog) and
the prepared twin of every packaging material (`<material item_code>_prepared`, resolved from the
material: same names and unit, `prepared_def`). Only preparations move them
(services/preparation_service.py: `source = preparation`, `preparation_id` set); their
breakdown (`item_detail`) lists preparations instead of batches: per preparation, the net of all
its movements (production step 3 takes sachets from it, reversals give them back). Reopening or
cancelling a preparation needs its own remaining contribution (`preparation_contributions`) to
cover what it takes back, otherwise INVENTORY_INSUFFICIENT. A twin follows its material's
kg <-> g switch (material_service). In the overview an archived material's twin stays only
while it has stock.
"""

import hashlib
import uuid
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import Select, and_, case, exists, func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.config import get_settings
from app.core.errors import AppError, ErrorCode
from app.inventory import units
from app.inventory.catalog import (
    CHICKEN,
    ITEMS,
    ITEMS_BY_CODE,
    MARINADE,
    MATERIAL_PREFIX,
    PACKS_BIG,
    PACKS_SMALL,
    PREPARED_SUFFIX,
    SATAY_SACHETS,
    SECTIONS,
    THIGHS,
    WASTED_THIGHS,
    WASTED_WINGS,
    WINGS,
    ItemDef,
    Section,
    byproduct_packed,
    byproduct_processed,
    is_material,
    is_prepared_twin,
    prepared_code,
    twin_base,
    wasted_byproduct,
    wasted_for,
)
from app.models import (
    InventoryBalance,
    InventoryMaterial,
    InventoryMovement,
    Order,
    Preparation,
    ProductionBatch,
    User,
    utcnow,
)
from app.production.catalog import BYPRODUCT_CODES
from app.schemas.common import UserRef
from app.schemas.inventory import (
    InventoryItemDetailOut,
    InventoryItemOut,
    InventoryOut,
    InventorySectionOut,
    InventoryUnit,
    ItemMaterialOut,
    ItemPreparationSourceOut,
    ItemSourceOut,
    MovementBatch,
    MovementOrder,
    MovementOut,
    MovementPage,
    MovementPreparation,
    MovementSource,
    SetValueIn,
    StockChangeOut,
)

KG_QUANT = Decimal("0.001")
MOVEMENTS_PAGE_SIZE = 50


@dataclass
class Delta:
    """One movement to write. `count` / `kg` / `g` / `m2` are signed; None for a unit the item
    doesn't track."""

    item_code: str
    count: int | None = None
    kg: Decimal | None = None
    g: Decimal | None = None
    m2: Decimal | None = None
    kg_estimated: bool = False
    step: int | None = None
    reversal_of: int | None = None
    reason: str | None = None
    # Per movement; `apply_movements(batch_id=...)` is the default for the batch.
    batch_id: uuid.UUID | None = None
    order_id: uuid.UUID | None = None
    preparation_id: uuid.UUID | None = None


def _kg(value: Decimal | None) -> Decimal:
    return (value or Decimal(0)).quantize(KG_QUANT, rounding=ROUND_HALF_UP)


def _g(value: Decimal | None) -> Decimal:
    return units.quantize("g", value or Decimal(0))


def _m2(value: Decimal | None) -> Decimal:
    return units.quantize("m2", value or Decimal(0))


def material_def(m: InventoryMaterial) -> ItemDef:
    """A material as an inventory item: Raw group, origin manual, exactly one unit."""
    return ItemDef(
        m.item_code,
        m.name_en,
        m.name_km,
        "stock",
        "raw",
        tracks_count=m.unit == "count",
        tracks_kg=m.unit == "kg",
        order=15,  # after Chicken (10), before the processed items
        origin="manual",
        tracks_g=m.unit == "g",
        tracks_m2=m.unit == "m2",
    )


def prepared_def(m: InventoryMaterial) -> ItemDef:
    """A packaging material's prepared twin: the material's names and unit, Prepared section."""
    return ItemDef(
        prepared_code(m.item_code),
        m.name_en,
        m.name_km,
        "prepared",
        "prepared",
        tracks_count=m.unit == "count",
        tracks_kg=m.unit == "kg",
        order=60,  # after the satay sachets
        origin="preparation",
        tracks_g=m.unit == "g",
        tracks_m2=m.unit == "m2",
    )


def unit_of(item: ItemDef) -> InventoryUnit:
    """A material's single unit; production items report their main unit (count first)."""
    if item.tracks_g:
        return "g"
    if item.tracks_m2:
        return "m2"
    return "count" if item.tracks_count else "kg"


async def materials_by_code(
    session: AsyncSession, codes: list[str] | set[str] | None = None
) -> dict[str, InventoryMaterial]:
    """Materials (archived included) by item code; every one when `codes` is None."""
    stmt = select(InventoryMaterial)
    if codes is not None:
        wanted = [c for c in codes if is_material(c)]
        if not wanted:
            return {}
        stmt = stmt.where(InventoryMaterial.item_code.in_(wanted))
    return {m.item_code: m for m in await session.scalars(stmt)}


async def twin_materials(
    session: AsyncSession, codes: list[str] | set[str]
) -> dict[str, InventoryMaterial]:
    """For prepared twin codes, the material each belongs to (archived included)."""
    bases = {twin_base(c): c for c in codes if is_prepared_twin(c)}
    if not bases:
        return {}
    return {bases[code]: m for code, m in (await materials_by_code(session, list(bases))).items()}


async def resolve(session: AsyncSession, codes: list[str] | set[str]) -> dict[str, ItemDef]:
    """Catalog items, materials and prepared twins for `codes` (unknown codes are left out)."""
    result = {c: ITEMS_BY_CODE[c] for c in codes if c in ITEMS_BY_CODE}
    for code, m in (await materials_by_code(session, codes)).items():
        result[code] = material_def(m)
    for code, m in (await twin_materials(session, codes)).items():
        result[code] = prepared_def(m)
    return result


async def _item(session: AsyncSession, code: str) -> ItemDef:
    item = (await resolve(session, [code])).get(code)
    if item is None:
        raise AppError(404, ErrorCode.INVENTORY_ITEM_NOT_FOUND, "Unknown inventory item")
    return item


def _blank(item: ItemDef) -> dict[str, Any]:
    return {
        "item_code": item.code,
        "count": 0 if item.tracks_count else None,
        "kg": Decimal(0) if item.tracks_kg else None,
        "g": Decimal(0) if item.tracks_g else None,
        "m2": Decimal(0) if item.tracks_m2 else None,
    }


async def ensure_balances(session: AsyncSession, codes: list[str] | None = None) -> None:
    """A zero balance row for every catalog item, material and packaging material's prepared twin
    (or `codes`) that has none. Idempotent."""
    if codes is None:
        materials = list((await materials_by_code(session)).values())
        items = [
            *ITEMS,
            *(material_def(m) for m in materials),
            *(prepared_def(m) for m in materials if m.prep_role == "packaging"),
        ]
    else:
        resolved = await resolve(session, codes)
        items = [resolved[c] for c in codes if c in resolved]
    if not items:
        return
    await session.execute(
        pg_insert(InventoryBalance)
        .values([_blank(i) for i in items])
        .on_conflict_do_nothing(index_elements=[InventoryBalance.item_code])
    )


async def lock_balances(session: AsyncSession, codes: list[str]) -> dict[str, InventoryBalance]:
    """Create missing rows, then lock the balances of `codes` FOR UPDATE in item_code order."""
    codes = sorted(set(codes))
    if not codes:
        return {}
    await ensure_balances(session, codes)
    return {
        b.item_code: b
        for b in await session.scalars(
            select(InventoryBalance)
            .where(InventoryBalance.item_code.in_(codes))
            .order_by(InventoryBalance.item_code)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    }


def _short_entry(
    item: ItemDef,
    bal: InventoryBalance,
    needed_count: int | None,
    needed_kg: Decimal | None,
    needed_g: Decimal | None = None,
    needed_m2: Decimal | None = None,
) -> dict[str, Any]:
    return {
        "item_code": item.code,
        # Names included: whoever records production or orders may not see the inventory.
        "name_en": item.name_en,
        "name_km": item.name_km,
        "available_count": bal.count,
        "available_kg": str(bal.kg) if bal.kg is not None else None,
        "available_g": str(bal.g) if bal.g is not None else None,
        "available_m2": str(bal.m2) if bal.m2 is not None else None,
        "needed_count": needed_count,
        "needed_kg": str(needed_kg) if needed_kg is not None else None,
        "needed_g": str(needed_g) if needed_g is not None else None,
        "needed_m2": str(needed_m2) if needed_m2 is not None else None,
    }


def _insufficient(short: list[dict[str, Any]]) -> AppError:
    return AppError(
        409, ErrorCode.INVENTORY_INSUFFICIENT, "Not enough stock for this change", {"items": short}
    )


def _normalized(delta: Delta, item: ItemDef) -> Delta | None:
    """Keep only tracked units (a unit not given stays None); None when nothing changes."""
    count = delta.count if item.tracks_count else None
    kg = _kg(delta.kg) if item.tracks_kg and delta.kg is not None else None
    g = _g(delta.g) if item.tracks_g and delta.g is not None else None
    m2 = _m2(delta.m2) if item.tracks_m2 and delta.m2 is not None else None
    if not count and not kg and not g and not m2:
        return None
    delta.count, delta.kg, delta.g, delta.m2 = count, kg, g, m2
    return delta


async def apply_movements(
    session: AsyncSession,
    actor: User | None,
    deltas: list[Delta],
    *,
    source: MovementSource,
    batch_id: uuid.UUID | None = None,
    preparation_id: uuid.UUID | None = None,
) -> list[InventoryMovement]:
    """Lock, check, apply and record. Raises INVENTORY_INSUFFICIENT; never commits."""
    items = await resolve(session, {d.item_code for d in deltas})
    rows = [d for d in (_normalized(d, items[d.item_code]) for d in deltas) if d is not None]
    if not rows:
        return []
    codes = sorted({d.item_code for d in rows})
    balances = await lock_balances(session, codes)

    # Net change per item: refuse before writing anything if one would go below zero.
    zero = Decimal(0)
    net: dict[str, tuple[int, Decimal, Decimal, Decimal]] = {}
    for d in rows:
        c, k, g, a = net.get(d.item_code, (0, zero, zero, zero))
        net[d.item_code] = (
            c + (d.count or 0),
            k + (d.kg or zero),
            g + (d.g or zero),
            a + (d.m2 or zero),
        )
    short = []
    for code in codes:
        bal, (dc, dk, dg, da) = balances[code], net[code]
        count_short = bal.count is not None and bal.count + dc < 0
        kg_short = bal.kg is not None and bal.kg + dk < 0
        g_short = bal.g is not None and bal.g + dg < 0
        m2_short = bal.m2 is not None and bal.m2 + da < 0
        if count_short or kg_short or g_short or m2_short:
            short.append(
                _short_entry(
                    items[code],
                    bal,
                    -dc if bal.count is not None and dc < 0 else None,
                    -dk if bal.kg is not None and dk < 0 else None,
                    -dg if bal.g is not None and dg < 0 else None,
                    -da if bal.m2 is not None and da < 0 else None,
                )
            )
    if short:
        raise _insufficient(short)

    now = utcnow()
    written = []
    for d in rows:
        bal = balances[d.item_code]
        if d.count is not None:
            bal.count = (bal.count or 0) + d.count
        if d.kg is not None:
            bal.kg = (bal.kg or Decimal(0)) + d.kg
        if d.g is not None:
            bal.g = (bal.g or Decimal(0)) + d.g
        if d.m2 is not None:
            bal.m2 = (bal.m2 or Decimal(0)) + d.m2
        bal.updated_at = now
        movement = InventoryMovement(
            item_code=d.item_code,
            count_delta=d.count,
            kg_delta=d.kg,
            g_delta=d.g,
            m2_delta=d.m2,
            kg_estimated=d.kg_estimated,
            source=source,
            batch_id=d.batch_id or batch_id,
            order_id=d.order_id,
            preparation_id=d.preparation_id or preparation_id,
            step=d.step,
            reversal_of=d.reversal_of,
            reason=d.reason,
            balance_count_after=bal.count,
            balance_kg_after=bal.kg,
            balance_g_after=bal.g,
            balance_m2_after=bal.m2,
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


async def marinade_material(
    session: AsyncSession, *, lock: bool = False
) -> InventoryMaterial | None:
    """The Marinade sauce material. `lock`: a share lock, so a unit change waits for us."""
    stmt = select(InventoryMaterial).where(InventoryMaterial.system_code == MARINADE)
    if lock:
        stmt = stmt.with_for_update(read=True)
    return await session.scalar(stmt.execution_options(populate_existing=True))


def _marinade_delta(material: InventoryMaterial, grams: Decimal) -> Delta:
    """Take `grams` of marinade out, in the material's unit (g, or kg rounded to 3 decimals)."""
    if material.unit == "kg":
        return Delta(material.item_code, kg=-units.convert(grams, "g", "kg"), step=2)
    return Delta(material.item_code, g=-units.quantize("g", grams), step=2)


def sachets_used(batch: ProductionBatch) -> dict[str, int]:
    """Step 3's satay sachets used, by item code (zero sizes left out)."""
    packaging = batch.packaging
    if packaging is None:
        return {}
    used = {4: packaging.sachets_4_used, 2: packaging.sachets_2_used}
    return {SATAY_SACHETS[size]: n for size, n in used.items() if n}


async def finish_step(
    session: AsyncSession, actor: User, batch: ProductionBatch, step: int
) -> None:
    if not batch.inventory_tracked:
        return
    deltas = step_deltas(batch, step)
    if step == 2 and batch.output is not None and batch.output.marinade_g:
        material = await marinade_material(session, lock=True)
        if material is not None:
            deltas.append(_marinade_delta(material, batch.output.marinade_g))
    if step == 3 and (sachets := sachets_used(batch)):
        # Every balance of this Finish locked (item_code order) before the sources are read.
        await lock_balances(session, [*(d.item_code for d in deltas), *sachets])
        deltas += await _take_by_preparation(session, sachets, step=3)
    await apply_movements(session, actor, deltas, source="production", batch_id=batch.id)


async def preparation_contributions(
    session: AsyncSession, codes: list[str], *, preparation_id: uuid.UUID | None = None
) -> dict[str, list[tuple[uuid.UUID, int]]]:
    """Per counted prepared item, each preparation's current net count: the sum of all movements
    carrying it (every source). Oldest first, as in the item breakdown; zero nets included."""
    stmt = (
        select(
            InventoryMovement.item_code,
            InventoryMovement.preparation_id,
            func.coalesce(func.sum(InventoryMovement.count_delta), 0),
        )
        .join(Preparation, Preparation.id == InventoryMovement.preparation_id)
        .where(InventoryMovement.item_code.in_(codes))
        .group_by(InventoryMovement.item_code, InventoryMovement.preparation_id, Preparation.code)
        .order_by(func.min(InventoryMovement.created_at), Preparation.code)
    )
    if preparation_id is not None:
        stmt = stmt.where(InventoryMovement.preparation_id == preparation_id)
    result: dict[str, list[tuple[uuid.UUID, int]]] = {c: [] for c in codes}
    for code, p_id, count in await session.execute(stmt):
        result[code].append((p_id, int(count)))
    return result


async def _take_by_preparation(
    session: AsyncSession, needs: dict[str, int], **kwargs: Any
) -> list[Delta]:
    """Take `needs` (item code -> count) from the preparations, oldest first. A shortfall is left
    unattributed; `apply_movements` then refuses it with INVENTORY_INSUFFICIENT."""
    contributions = await preparation_contributions(session, sorted(needs))
    deltas: list[Delta] = []
    for code, need in sorted(needs.items()):
        left = need
        for p_id, net in contributions[code]:
            if left <= 0:
                break
            if net <= 0:
                continue
            take = min(net, left)
            deltas.append(Delta(code, count=-take, preparation_id=p_id, **kwargs))
            left -= take
        if left > 0:
            deltas.append(Delta(code, count=-left, **kwargs))
    return deltas


async def counts_in_stock(session: AsyncSession, codes: list[str]) -> dict[str, int]:
    """Current count balances of `codes` (not locked); 0 without a row."""
    rows = {
        b.item_code: b.count
        for b in await session.scalars(
            select(InventoryBalance).where(InventoryBalance.item_code.in_(codes))
        )
    }
    return {code: int(rows.get(code) or 0) for code in codes}


async def marinade_stock(session: AsyncSession) -> tuple[InventoryUnit, Decimal] | None:
    """The Marinade sauce balance in its own unit (for the step 2 form)."""
    material = await marinade_material(session)
    if material is None:
        return None
    bal = await session.get(InventoryBalance, material.item_code)
    item = material_def(material)
    unit = unit_of(item)
    if bal is None:
        return unit, Decimal(0)
    return unit, Decimal({"count": bal.count, "kg": bal.kg, "g": bal.g, "m2": bal.m2}[unit] or 0)


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
    materials = await materials_by_code(session, {m.item_code for m in originals})
    deltas = [
        _in_current_unit(
            Delta(
                m.item_code,
                -m.count_delta if m.count_delta is not None else None,
                -m.kg_delta if m.kg_delta is not None else None,
                -m.g_delta if m.g_delta is not None else None,
                -m.m2_delta if m.m2_delta is not None else None,
                kg_estimated=m.kg_estimated,
                step=m.step,
                reversal_of=m.id,
                reason=cause,
                preparation_id=m.preparation_id,
            ),
            materials.get(m.item_code),
        )
        for m in originals
    ]
    # Materials (the marinade) aren't attributed to batches: only production items are guarded.
    await _guard_reversal(session, batch, [d for d in deltas if d.item_code in ITEMS_BY_CODE])
    await apply_movements(session, actor, deltas, source="production", batch_id=batch.id)


def _in_current_unit(delta: Delta, material: InventoryMaterial | None) -> Delta:
    """A material's movement may predate a kg <-> g switch: express it in today's unit."""
    if material is None or material.unit == "count":
        return delta
    if material.unit == "g" and delta.kg is not None:
        delta.g, delta.kg = units.convert(delta.kg, "kg", "g"), None
    elif material.unit == "kg" and delta.g is not None:
        delta.kg, delta.g = units.convert(delta.g, "g", "kg"), None
    return delta


async def batch_contributions(
    session: AsyncSession, codes: list[str], *, batch_id: uuid.UUID | None = None
) -> dict[str, list[tuple[uuid.UUID, int, Decimal]]]:
    """Per item, each batch's current net contribution `(batch_id, count, kg)`: the sum of all
    the batch's movements of that item (every source). Oldest batch first; zero nets included."""
    stmt = (
        select(
            InventoryMovement.item_code,
            InventoryMovement.batch_id,
            func.coalesce(func.sum(InventoryMovement.count_delta), 0),
            func.coalesce(func.sum(InventoryMovement.kg_delta), 0),
        )
        .join(ProductionBatch, ProductionBatch.id == InventoryMovement.batch_id)
        .where(InventoryMovement.item_code.in_(codes))
        .group_by(
            InventoryMovement.item_code,
            InventoryMovement.batch_id,
            ProductionBatch.created_at,
            ProductionBatch.code,
        )
        .order_by(ProductionBatch.created_at, ProductionBatch.code)
    )
    if batch_id is not None:
        stmt = stmt.where(InventoryMovement.batch_id == batch_id)
    result: dict[str, list[tuple[uuid.UUID, int, Decimal]]] = {c: [] for c in codes}
    for code, b_id, count, kg in await session.execute(stmt):
        result[code].append((b_id, int(count), Decimal(kg)))
    return result


async def _guard_reversal(
    session: AsyncSession, batch: ProductionBatch, deltas: list[Delta]
) -> None:
    """A reversal may only take back what the batch still has: if part of what it made already
    left in orders, refuse with PRODUCTION_STOCK_ALREADY_USED (nothing is written)."""
    needed: dict[str, tuple[int, Decimal]] = {}
    for d in deltas:
        c, k = needed.get(d.item_code, (0, Decimal(0)))
        needed[d.item_code] = (c - (d.count or 0), k - (d.kg or Decimal(0)))
    codes = sorted(code for code, (c, k) in needed.items() if c > 0 or k > 0)
    if not codes:
        return
    # Locked first: an order delivering these items waits, then sees the reversal (or refuses).
    await lock_balances(session, codes)
    own = await batch_contributions(session, codes, batch_id=batch.id)
    short = []
    for code in codes:
        item = ITEMS_BY_CODE[code]
        have_c = sum(c for _, c, _ in own[code])
        have_k = sum((k for _, _, k in own[code]), Decimal(0))
        need_c, need_k = needed[code]
        if (item.tracks_count and have_c < need_c) or (item.tracks_kg and have_k < need_k):
            short.append((item, have_c, have_k, need_c, need_k))
    if not short:
        return
    order_codes = await _orders_using(session, batch.id, [i.code for i, *_ in short])
    raise AppError(
        409,
        ErrorCode.PRODUCTION_STOCK_ALREADY_USED,
        "Stock from this batch already left in orders",
        {
            "items": [
                {
                    "item_code": item.code,
                    "name_en": item.name_en,
                    "name_km": item.name_km,
                    "remaining_count": have_c if item.tracks_count else None,
                    "remaining_kg": str(_kg(have_k)) if item.tracks_kg else None,
                    "needed_count": need_c if item.tracks_count else None,
                    "needed_kg": str(_kg(need_k)) if item.tracks_kg else None,
                    "orders": order_codes.get(item.code, []),
                }
                for item, have_c, have_k, need_c, need_k in short
            ],
            "orders": sorted({c for codes_ in order_codes.values() for c in codes_}),
        },
    )


async def _orders_using(
    session: AsyncSession, batch_id: uuid.UUID, codes: list[str]
) -> dict[str, list[str]]:
    """Per item, the codes of the orders that took this batch's stock of it."""
    rows = await session.execute(
        select(InventoryMovement.item_code, Order.code)
        .join(Order, Order.id == InventoryMovement.order_id)
        .where(
            InventoryMovement.batch_id == batch_id,
            InventoryMovement.source == "order",
            InventoryMovement.item_code.in_(codes),
        )
        .distinct()
        .order_by(InventoryMovement.item_code, Order.code)
    )
    result: dict[str, list[str]] = {}
    for code, order_code in rows:
        result.setdefault(code, []).append(order_code)
    return result


# --- Orders --------------------------------------------------------------------------------------

# Quantities of orderable items, each in its own unit: a whole count (packs) or kg (by-products).
Quantities = dict[str, Decimal]


def _qty_delta(code: str, qty: Decimal, **kwargs: Any) -> Delta:
    if ITEMS_BY_CODE[code].tracks_count:
        return Delta(code, count=int(qty), **kwargs)
    return Delta(code, kg=qty, **kwargs)


def _amount(item: ItemDef, count: int | None, kg: Decimal | None) -> Decimal:
    """A balance or net in the item's own unit."""
    return Decimal(count or 0) if item.tracks_count else Decimal(kg or 0)


async def available(session: AsyncSession, codes: list[str]) -> Quantities:
    """Current balances of `codes` in each item's unit (not locked)."""
    rows = {
        b.item_code: b
        for b in await session.scalars(
            select(InventoryBalance).where(InventoryBalance.item_code.in_(codes))
        )
    }
    result: Quantities = {}
    for code in codes:
        bal = rows.get(code)
        result[code] = _amount(ITEMS_BY_CODE[code], bal.count, bal.kg) if bal else Decimal(0)
    return result


async def take_for_order(
    session: AsyncSession, actor: User, order: Order, totals: Quantities
) -> None:
    """Delivering: remove the order's totals from stock, oldest batch first, one movement per
    (item, batch). Refuses with INVENTORY_INSUFFICIENT (per item: available, needed) without
    writing anything."""
    codes = sorted(code for code, qty in totals.items() if qty > 0)
    balances = await lock_balances(session, codes)
    contributions = await batch_contributions(session, codes)
    deltas: list[Delta] = []
    short = []
    for code in codes:
        item, need, bal = ITEMS_BY_CODE[code], totals[code], balances[code]
        if _amount(item, bal.count, bal.kg) < need:
            short.append(
                _short_entry(
                    item,
                    bal,
                    int(need) if item.tracks_count else None,
                    None if item.tracks_count else _kg(need),
                )
            )
            continue
        left = need
        for b_id, count, kg in contributions[code]:
            net = _amount(item, count, kg)
            if left <= 0:
                break
            if net <= 0:
                continue
            take = min(net, left)
            deltas.append(_qty_delta(code, -take, batch_id=b_id, order_id=order.id))
            left -= take
        if left > 0:
            # Stock attributed to no batch (not expected: every movement has one).
            deltas.append(_qty_delta(code, -left, order_id=order.id))
    if short:
        raise _insufficient(short)
    await apply_movements(session, actor, deltas, source="order")


def _spread(slots: list[list[Any]], qty: Decimal) -> list[tuple[uuid.UUID | None, Decimal]]:
    """Take `qty` from `slots` ([batch_id, room], in order), reducing their room."""
    out: list[tuple[uuid.UUID | None, Decimal]] = []
    left = qty
    for slot in slots:
        if left <= 0:
            break
        give = min(slot[1], left)
        if give > 0:
            out.append((slot[0], give))
            slot[1] -= give
            left -= give
    if left > 0:
        # More than the order took from its batches (validation prevents it): the last batch.
        out.append((slots[-1][0] if slots else None, left))
    return out


async def return_from_order(
    session: AsyncSession, actor: User, order: Order, to_stock: Quantities, to_wasted: Quantities
) -> None:
    """Return review: what goes back to stock returns to the batches the order took it from,
    newest first; what is wasted continues the same split into the item's wasted item."""
    codes = sorted({*to_stock, *to_wasted})
    if not codes:
        return
    rows = await session.execute(
        select(
            InventoryMovement.item_code,
            InventoryMovement.batch_id,
            func.coalesce(func.sum(InventoryMovement.count_delta), 0),
            func.coalesce(func.sum(InventoryMovement.kg_delta), 0),
        )
        .outerjoin(ProductionBatch, ProductionBatch.id == InventoryMovement.batch_id)
        .where(
            InventoryMovement.order_id == order.id,
            InventoryMovement.source == "order",
            InventoryMovement.item_code.in_(codes),
        )
        .group_by(
            InventoryMovement.item_code,
            InventoryMovement.batch_id,
            ProductionBatch.created_at,
            ProductionBatch.code,
        )
        # Newest batch first (stock without a batch last).
        .order_by(ProductionBatch.created_at.desc().nulls_last(), ProductionBatch.code.desc())
    )
    slots: dict[str, list[list[Any]]] = {c: [] for c in codes}
    for code, b_id, count, kg in rows:
        # The order's movements are negative: what it took is their opposite.
        slots[code].append([b_id, -_amount(ITEMS_BY_CODE[code], int(count), Decimal(kg))])

    deltas: list[Delta] = []
    for code in codes:
        for target, qty in ((code, to_stock.get(code)), (wasted_for(code), to_wasted.get(code))):
            if qty:
                deltas += [
                    _qty_delta(target, give, batch_id=b_id, order_id=order.id)
                    for b_id, give in _spread(slots[code], qty)
                ]
    await apply_movements(session, actor, deltas, source="order_return")


async def stock_changes(session: AsyncSession, batch: ProductionBatch) -> list[StockChangeOut]:
    """Net effect of the batch's finished steps (reversed movements left out), one row per
    (step, item): the satay sachets of step 3 are split across preparations, summed here."""
    if not batch.inventory_tracked:
        return []
    order = {i.code: i.order for i in ITEMS}
    rows = sorted(
        await session.scalars(_open_movements(batch.id)),
        key=lambda m: (m.step or 0, order.get(m.item_code, 15), m.id),
    )
    items = await resolve(session, {m.item_code for m in rows})

    def add(a: Any, b: Any) -> Any:
        return b if a is None else a if b is None else a + b

    merged: dict[tuple[int, str], StockChangeOut] = {}
    for m in rows:
        key = (m.step or 0, m.item_code)
        if key in merged:
            row = merged[key]
            row.count_delta = add(row.count_delta, m.count_delta)
            row.kg_delta = add(row.kg_delta, m.kg_delta)
            row.g_delta = add(row.g_delta, m.g_delta)
            row.m2_delta = add(row.m2_delta, m.m2_delta)
            row.kg_estimated = row.kg_estimated or m.kg_estimated
            continue
        merged[key] = StockChangeOut(
            step=m.step or 0,
            item_code=m.item_code,
            section=_section(items, m.item_code),
            name_en=_names(items, m.item_code)[0],
            name_km=_names(items, m.item_code)[1],
            count_delta=m.count_delta,
            kg_delta=m.kg_delta,
            g_delta=m.g_delta,
            m2_delta=m.m2_delta,
            kg_estimated=m.kg_estimated,
        )
    return list(merged.values())


# --- Setting a value -----------------------------------------------------------------------------


async def set_value(session: AsyncSession, actor: User, item_code: str, data: SetValueIn) -> None:
    """Refused for every item, for everyone (the superadmin included): production items change
    only through production, materials through add / remove (`/inventory/materials/{id}/...`).
    Kept so old clients get a clear error instead of a 404."""
    item = await _item(session, item_code)
    details: dict[str, Any] = {"item_code": item.code}
    if item.origin == "manual":
        details["use"] = "material_add_remove"
    raise AppError(
        409,
        ErrorCode.INVENTORY_ITEM_PRODUCTION_ONLY,
        "This item's stock can't be set directly",
        details,
    )


# --- Reading -------------------------------------------------------------------------------------


def _section(items: dict[str, ItemDef], code: str) -> Section | None:
    item = items.get(code)
    return item.section if item else None


def _names(items: dict[str, ItemDef], code: str) -> tuple[str, str]:
    item = items.get(code)
    # An item removed from the catalog keeps its history under its code.
    return (item.name_en, item.name_km) if item else (code, code)


def material_icon_url(m: InventoryMaterial) -> str | None:
    """The uploaded icon's path, versioned by `updated_at` (an upload touches it), so clients can
    cache it by URL. None without an uploaded icon."""
    if m.icon_mime is None:
        return None
    version = hashlib.sha1(m.updated_at.isoformat().encode()).hexdigest()[:10]
    return f"/inventory/materials/{m.id}/icon?v={version}"


def _material_out(m: InventoryMaterial | None) -> ItemMaterialOut | None:
    if m is None:
        return None
    return ItemMaterialOut(
        id=m.id,
        unit=m.unit,  # type: ignore[arg-type]
        system_code=m.system_code,
        archived=m.archived_at is not None,
        icon_key=m.icon_key,
        icon_url=material_icon_url(m),
        prep_role=m.prep_role,  # type: ignore[arg-type]
    )


def _item_out(
    item: ItemDef,
    bal: InventoryBalance | None,
    last_change: datetime | None,
    material: InventoryMaterial | None = None,
) -> InventoryItemOut:
    return InventoryItemOut(
        code=item.code,
        section=item.section,
        group=item.group,
        name_en=item.name_en,
        name_km=item.name_km,
        tracks_count=item.tracks_count,
        tracks_kg=item.tracks_kg,
        tracks_g=item.tracks_g,
        tracks_m2=item.tracks_m2,
        kg_estimated=item.kg_estimated,
        origin=item.origin,
        count=(bal.count if bal and bal.count is not None else 0) if item.tracks_count else None,
        kg=(bal.kg if bal and bal.kg is not None else Decimal(0)) if item.tracks_kg else None,
        g=(bal.g if bal and bal.g is not None else Decimal(0)) if item.tracks_g else None,
        m2=(bal.m2 if bal and bal.m2 is not None else Decimal(0)) if item.tracks_m2 else None,
        # None: never changed.
        updated_at=last_change,
        material=_material_out(material),
    )


async def item_detail(session: AsyncSession, item_code: str) -> InventoryItemDetailOut:
    """One item with its balance and, per batch, what it currently contributes.

    A batch's contribution is the sum of all its movements for the item, every source: production
    (reversals included), orders taken from it (oldest batch first) and returns given back to it.
    So the contributions add up to the balance. Materials have no per-batch breakdown.
    """
    item = await _item(session, item_code)
    material = (await materials_by_code(session, [item.code])).get(item.code)
    bal = await session.get(InventoryBalance, item.code)
    last = await session.scalar(
        select(func.max(InventoryMovement.created_at)).where(
            InventoryMovement.item_code == item.code
        )
    )
    if item.origin == "preparation":
        twin_of = (await twin_materials(session, [item.code])).get(item.code)
        return InventoryItemDetailOut(
            **_item_out(item, bal, last, twin_of).model_dump(),
            sources=[],
            preparation_sources=await _preparation_sources(session, item),
        )
    if material is not None:
        return InventoryItemDetailOut(
            **_item_out(item, bal, last, material).model_dump(), sources=[]
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
            .where(InventoryMovement.item_code == item.code)
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
            # Only order movements (e.g. wasted packs from a return): packs come from step 3.
            last_step=int(step or 3),
        )
        for batch_id, code, count, kg, estimated, step in rows
        if (item.tracks_count and count) or (item.tracks_kg and kg)
    ]
    return InventoryItemDetailOut(**_item_out(item, bal, last).model_dump(), sources=sources)


async def _preparation_sources(
    session: AsyncSession, item: ItemDef
) -> list[ItemPreparationSourceOut]:
    """Per preparation, the net quantity it currently adds to a prepared item (its movements,
    reversals included): non-zero only, oldest first. The totals equal the balance."""
    rows = await session.execute(
        select(
            Preparation.id,
            Preparation.code,
            Preparation.prepared_date,
            func.coalesce(func.sum(InventoryMovement.count_delta), 0),
            func.coalesce(func.sum(InventoryMovement.kg_delta), 0),
            func.coalesce(func.sum(InventoryMovement.g_delta), 0),
            func.coalesce(func.sum(InventoryMovement.m2_delta), 0),
        )
        .join(Preparation, Preparation.id == InventoryMovement.preparation_id)
        .where(InventoryMovement.item_code == item.code)
        .group_by(Preparation.id, Preparation.code, Preparation.prepared_date)
        .order_by(func.min(InventoryMovement.created_at), Preparation.code)
    )
    return [
        ItemPreparationSourceOut(
            preparation_id=p_id,
            code=code,
            prepared_date=prepared_date,
            count=int(count) if item.tracks_count else None,
            kg=Decimal(kg) if item.tracks_kg else None,
            g=Decimal(g) if item.tracks_g else None,
            m2=Decimal(m2) if item.tracks_m2 else None,
        )
        for p_id, code, prepared_date, count, kg, g, m2 in rows
        if (item.tracks_count and count)
        or (item.tracks_kg and kg)
        or (item.tracks_g and g)
        or (item.tracks_m2 and m2)
    ]


def _has_stock(bal: InventoryBalance | None) -> bool:
    return bal is not None and bool(bal.count or bal.kg or bal.g or bal.m2)


async def overview(session: AsyncSession) -> InventoryOut:
    """Every catalog item and every active material (Raw, after Chicken), by section; the
    prepared twins after the satay sachets (an archived material's only while it has stock)."""
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
    every_material = sorted(
        (await materials_by_code(session)).values(), key=lambda m: m.name_en.lower()
    )
    materials = [m for m in every_material if m.archived_at is None]
    twins = [
        m
        for m in every_material
        if (m.archived_at is None and m.prep_role == "packaging")
        or _has_stock(balances.get(prepared_code(m.item_code)))
    ]
    sections = []
    for section in SECTIONS:
        items = []
        for item in (i for i in ITEMS if i.section == section):
            items.append(_item_out(item, balances.get(item.code), last.get(item.code)))
            if item.code == CHICKEN:
                items += [
                    _item_out(material_def(m), balances.get(m.item_code), last.get(m.item_code), m)
                    for m in materials
                ]
        if section == "prepared":
            for m in twins:
                code = prepared_code(m.item_code)
                items.append(_item_out(prepared_def(m), balances.get(code), last.get(code), m))
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
    order_id: uuid.UUID | None = None,
    preparation_id: uuid.UUID | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    page: int = 1,
    page_size: int = MOVEMENTS_PAGE_SIZE,
) -> MovementPage:
    conditions = []
    if item_code:
        conditions.append(InventoryMovement.item_code == item_code)
    if section:
        in_section = InventoryMovement.item_code.in_(
            [i.code for i in ITEMS if i.section == section]
        )
        # Materials are all in stock (Raw); their prepared twins in prepared.
        is_material_code = InventoryMovement.item_code.like(f"{MATERIAL_PREFIX}%")
        is_twin_code = and_(
            is_material_code, InventoryMovement.item_code.like(f"%{PREPARED_SUFFIX}")
        )
        if section == "stock":
            in_section = or_(in_section, and_(is_material_code, ~is_twin_code))
        elif section == "prepared":
            in_section = or_(in_section, is_twin_code)
        conditions.append(in_section)
    if source:
        conditions.append(InventoryMovement.source == source)
    if batch_id:
        conditions.append(InventoryMovement.batch_id == batch_id)
    if order_id:
        conditions.append(InventoryMovement.order_id == order_id)
    if preparation_id:
        conditions.append(InventoryMovement.preparation_id == preparation_id)
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
    order_ids = {m.order_id for m in rows if m.order_id}
    orders = (
        {
            o.id: o.code
            for o in await session.execute(
                select(Order.id, Order.code).where(Order.id.in_(order_ids))
            )
        }
        if order_ids
        else {}
    )
    preparation_ids = {m.preparation_id for m in rows if m.preparation_id}
    preparations = (
        {
            p.id: p.code
            for p in await session.execute(
                select(Preparation.id, Preparation.code).where(Preparation.id.in_(preparation_ids))
            )
        }
        if preparation_ids
        else {}
    )
    items = await resolve(session, {m.item_code for m in rows})
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
                section=_section(items, m.item_code),
                name_en=_names(items, m.item_code)[0],
                name_km=_names(items, m.item_code)[1],
                count_delta=m.count_delta,
                kg_delta=m.kg_delta,
                g_delta=m.g_delta,
                m2_delta=m.m2_delta,
                kg_estimated=m.kg_estimated,
                source=m.source,  # type: ignore[arg-type]
                batch=MovementBatch(id=m.batch_id, code=codes[m.batch_id])
                if m.batch_id in codes
                else None,
                order=MovementOrder(id=m.order_id, code=orders[m.order_id])
                if m.order_id in orders
                else None,
                preparation=MovementPreparation(
                    id=m.preparation_id, code=preparations[m.preparation_id]
                )
                if m.preparation_id in preparations
                else None,
                step=m.step,
                reversal_of=m.reversal_of,
                reason=m.reason,
                balance_count_after=m.balance_count_after,
                balance_kg_after=m.balance_kg_after,
                balance_g_after=m.balance_g_after,
                balance_m2_after=m.balance_m2_after,
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
