"""Packaging plans: how many 4-piece (big) and 2-piece (small) packs step 3 should make.

The plan row is created and reset by production_service (step 2 Finish, reopen). Here: listing,
reading, saving and confirming. Every write locks the batch row and uses the batch `version`
(PRODUCTION_CONFLICT when stale), like the steps. Checks run in this order: not found, cancelled,
locked (step 3 finished → PRODUCTION_PLAN_LOCKED), step 2 not finished (PRODUCTION_STEP_NOT_READY),
version, then the values.

- Planned pieces = 2 × big + small; they must fit in the produced wings **and** thighs
  (PRODUCTION_PLAN_EXCEEDS_OUTPUT), checked on save (when both values are set) and on confirm.
- Confirm needs both values (VALIDATION_ERROR). Editing a confirmed plan keeps it confirmed.
"""

import uuid
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, ErrorCode
from app.models import (
    ProductionBatch,
    ProductionOutput,
    ProductionPlan,
    ProductionRawMaterial,
    Supplier,
    User,
    utcnow,
)
from app.production.catalog import BYPRODUCT_CODES, BYPRODUCTS_BY_CODE
from app.schemas.production import (
    ActualPacks,
    PlanDetail,
    PlanListItem,
    PlanListStatus,
    PlanPage,
    PlanUpdate,
    ProducedByproductOut,
    ProducedSummary,
)
from app.services import production_service as prod
from app.services.audit_service import record

PLAN_FIELDS = ("expected_big", "expected_small", "note")


def editable(batch: ProductionBatch) -> bool:
    return (
        batch.status == "in_progress"
        and batch.plan is not None
        and batch.output is not None
        and batch.output.finished
        and (batch.packaging is None or not batch.packaging.finished)
    )


async def _for_write(
    session: AsyncSession, batch_id: uuid.UUID, version: int, actor: User
) -> tuple[ProductionBatch, ProductionPlan]:
    batch = await prod._for_write(session, batch_id)  # not found, cancelled
    if batch.status == "completed" or (batch.packaging is not None and batch.packaging.finished):
        raise AppError(
            409,
            ErrorCode.PRODUCTION_PLAN_LOCKED,
            "Step 3 is finished; reopen it to change the plan",
        )
    if batch.plan is None or batch.output is None or not batch.output.finished:
        raise AppError(
            409,
            ErrorCode.PRODUCTION_STEP_NOT_READY,
            "Step 2 must be finished before the plan can be set",
        )
    await prod._check_version(session, batch, version, actor)
    return batch, batch.plan


def _check_fits(batch: ProductionBatch, plan: ProductionPlan) -> None:
    if plan.expected_big is None or plan.expected_small is None:
        return
    output = batch.output
    assert output is not None
    planned = 2 * plan.expected_big + plan.expected_small
    available = {"wings": output.wings_count, "thighs": output.thighs_count}
    if any(planned > count for count in available.values()):
        raise AppError(
            422,
            ErrorCode.PRODUCTION_PLAN_EXCEEDS_OUTPUT,
            "The plan uses more pieces than were produced",
            {piece: {"available": count, "planned": planned} for piece, count in available.items()},
        )


def _touch(batch: ProductionBatch, plan: ProductionPlan, actor: User) -> None:
    now = utcnow()
    plan.updated_by = actor.id
    plan.updated_at = now
    batch.updated_by = actor.id
    batch.updated_at = now
    batch.version += 1


def _audit(
    session: AsyncSession, action: str, actor: User, batch: ProductionBatch, **details: Any
) -> None:
    record(
        session,
        action,
        actor_id=actor.id,
        entity_type=prod.ENTITY,
        entity_id=batch.id,
        details={"code": batch.code, **details},
    )


async def update_plan(
    session: AsyncSession, actor: User, batch_id: uuid.UUID, data: PlanUpdate
) -> ProductionBatch:
    batch, plan = await _for_write(session, batch_id, data.version, actor)
    fields = data.model_fields_set - {"version"}
    changes: dict[str, list[Any]] = {}
    for attr in PLAN_FIELDS:
        if attr not in fields:
            continue
        value = getattr(data, attr)
        if attr == "note":
            value = (value or "").strip() or None
        elif value is None and plan.confirmed:
            raise prod._invalid(
                [prod._field_error(["body", attr], "missing", "A confirmed plan needs a value")]
            )
        if getattr(plan, attr) != value:
            changes[attr] = [getattr(plan, attr), value]
            setattr(plan, attr, value)
    _check_fits(batch, plan)
    _touch(batch, plan, actor)
    if changes:
        _audit(session, "production_plan.update", actor, batch, changes=changes)
    await session.commit()
    return await prod.get_batch(session, batch_id)


async def confirm_plan(
    session: AsyncSession, actor: User, batch_id: uuid.UUID, version: int
) -> ProductionBatch:
    batch, plan = await _for_write(session, batch_id, version, actor)
    missing = [
        prod._field_error(["plan", attr], "missing", "Required")
        for attr in ("expected_big", "expected_small")
        if getattr(plan, attr) is None
    ]
    if missing:
        raise prod._invalid(missing, "Set both pack counts before confirming")
    _check_fits(batch, plan)
    now = utcnow()
    plan.status = "confirmed"
    plan.confirmed_by = actor.id
    plan.confirmed_at = now
    _touch(batch, plan, actor)
    _audit(
        session,
        "production_plan.confirm",
        actor,
        batch,
        expected_big=plan.expected_big,
        expected_small=plan.expected_small,
    )
    await session.commit()
    return await prod.get_batch(session, batch_id)


# --- Reading -------------------------------------------------------------------------------------


async def list_plans(
    session: AsyncSession, *, status: PlanListStatus, q: str | None, page: int, page_size: int
) -> PlanPage:
    b, pl, o, r, s = (
        ProductionBatch,
        ProductionPlan,
        ProductionOutput,
        ProductionRawMaterial,
        Supplier,
    )
    stage = {
        "pending": [b.status == "in_progress", pl.status == "pending"],
        "confirmed": [b.status == "in_progress", pl.status == "confirmed"],
        "completed": [b.status == "completed"],
        # Cancelled batches never show up here.
        "all": [b.status != "cancelled"],
    }
    conditions: list[Any] = list(stage[status])
    if q and q.strip():
        pattern = f"%{prod._escape_like(q.strip())}%"
        conditions.append(
            or_(b.code.ilike(pattern, escape="\\"), s.name.ilike(pattern, escape="\\"))
        )

    def _from(stmt):
        return (
            stmt.join(pl, pl.batch_id == b.id)
            .join(r, r.batch_id == b.id)
            .join(o, o.batch_id == b.id)
            .outerjoin(s, s.id == r.supplier_id)
        )

    total = await session.scalar(_from(select(func.count(b.id))).where(*conditions)) or 0
    pending = await session.scalar(_from(select(func.count(b.id))).where(*stage["pending"])) or 0
    batches = list(
        await session.scalars(
            _from(select(b))
            .where(*conditions)
            .order_by(o.production_date.desc().nulls_first(), b.code.desc(), b.id)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    )
    suppliers = await prod._suppliers(
        session, {x.raw_material.supplier_id for x in batches if x.raw_material.supplier_id}
    )
    items = []
    for x in batches:
        assert x.plan is not None and x.output is not None
        items.append(
            PlanListItem(
                batch_id=x.id,
                code=x.code,
                batch_status=x.status,
                supplier=prod._brief(suppliers.get(x.raw_material.supplier_id))
                if x.raw_material.supplier_id
                else None,
                production_date=x.output.production_date,
                quantity=x.raw_material.quantity,
                wings_count=x.output.wings_count,
                thighs_count=x.output.thighs_count,
                status=x.plan.status,
                expected_big=x.plan.expected_big,
                expected_small=x.plan.expected_small,
                updated_at=x.plan.updated_at,
            )
        )
    return PlanPage(items=items, total=total, page=page, page_size=page_size, pending_count=pending)


async def pending_count(session: AsyncSession) -> int:
    return (
        await session.scalar(
            select(func.count(ProductionPlan.batch_id))
            .join(ProductionBatch, ProductionBatch.id == ProductionPlan.batch_id)
            .where(ProductionBatch.status == "in_progress", ProductionPlan.status == "pending")
        )
        or 0
    )


async def plan_detail(session: AsyncSession, batch: ProductionBatch) -> PlanDetail:
    users = await prod._users(session, prod._user_ids(batch))
    raw, output, packaging = batch.raw_material, batch.output, batch.packaging
    supplier = await session.get(Supplier, raw.supplier_id) if raw.supplier_id else None
    rows = {b.item_code: b for b in batch.byproducts}
    produced = None
    if output is not None:
        produced = ProducedSummary(
            status=output.status,
            production_date=output.production_date,
            wings_kg=output.wings_kg,
            thighs_kg=output.thighs_kg,
            wings_count=output.wings_count,
            thighs_count=output.thighs_count,
            marinade_g=output.marinade_g,
            byproducts=[
                ProducedByproductOut(
                    item_code=code,
                    name_en=BYPRODUCTS_BY_CODE[code].name_en,
                    name_km=BYPRODUCTS_BY_CODE[code].name_km,
                    produced_kg=rows[code].produced_kg if code in rows else None,
                )
                for code in BYPRODUCT_CODES
            ],
        )
    return PlanDetail(
        batch_id=batch.id,
        code=batch.code,
        batch_status=batch.status,
        current_step=batch.current_step,
        version=batch.version,
        supplier=prod._brief(supplier),
        quantity=raw.quantity,
        produced=produced,
        standardize=None
        if packaging is None
        else ActualPacks(
            status=packaging.status,
            big_packages=packaging.big_packages,
            small_packages=packaging.small_packages,
            comment=packaging.comment,
            packaging_date=packaging.packaging_date,
        ),
        plan=prod.plan_out(batch.plan, users),
        plan_legacy=prod.plan_legacy(batch),
        editable=editable(batch),
    )
