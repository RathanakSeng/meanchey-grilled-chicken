"""Production batches: three steps, drafts with optimistic versioning, finish / reopen / cancel.

Every write locks the batch row (`SELECT … FOR UPDATE`), checks its state, then compares the
client's `version` with the stored one (stale → PRODUCTION_CONFLICT with the current batch), and
increments `version`. Checks run in this order: not found, cancelled, step state (not ready /
finished / locked), version, then the values.

Rules enforced here:
- A step can be edited or finished only after the previous one is finished.
- Piece counts (step 2) are always quantity × pieces per unit; clients can't set them.
- Finishing step 3 requires the piece balance (PRODUCTION_BALANCE_MISMATCH). The by-product
  balance (carry + rejected = produced) is a UI-only rule and deliberately NOT checked here.
"""

import re
import uuid
from datetime import date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.errors import AppError, ErrorCode
from app.core.phones import format_phone
from app.models import (
    ProductionBatch,
    ProductionBatchCounter,
    ProductionByproduct,
    ProductionOutput,
    ProductionPackaging,
    ProductionRawMaterial,
    Supplier,
    User,
    utcnow,
)
from app.production.catalog import (
    BYPRODUCT_CODES,
    BYPRODUCTS,
    BYPRODUCTS_BY_CODE,
    DEFAULT_MATERIAL_KIND,
    MATERIAL_KINDS,
    MATERIAL_KINDS_BY_CODE,
    MaterialKindDef,
)
from app.schemas.common import UserRef
from app.schemas.production import (
    BatchListItem,
    BatchOut,
    ByproductCatalogOut,
    ByproductOut,
    CatalogOut,
    ComputedOut,
    ListStatus,
    MaterialKindCatalogOut,
    ProducedDraft,
    ProducedOut,
    ProductionCreate,
    ProductionSort,
    ProductionStats,
    RawMaterialFields,
    RawMaterialOut,
    StandardizeDraft,
    StandardizeOut,
    SupplierBrief,
    SupplierOption,
)
from app.services.audit_service import record

ENTITY = "production_batch"
STEP_NUMBERS: dict[str, int] = {"raw-material": 1, "produced": 2, "standardize": 3}
SUPPLIER_OPTIONS_LIMIT = 20

_NON_DIGITS = re.compile(r"\D+")

StepRow = ProductionRawMaterial | ProductionOutput | ProductionPackaging


# --- Calendar and codes --------------------------------------------------------------------------


def business_today(now: datetime | None = None) -> date:
    return (now or utcnow()).astimezone(get_settings().business_tz).date()


def _local_midnight(day: date) -> datetime:
    return datetime.combine(day, time(), tzinfo=get_settings().business_tz)


async def next_code(session: AsyncSession, day: date) -> str:
    """PR-YYYYMMDD-NNN. The counter row is locked until the transaction ends, so concurrent
    creations on the same day get distinct numbers."""
    counter = ProductionBatchCounter.__table__
    stmt = (
        pg_insert(counter)
        .values(day=day, last_number=1)
        .on_conflict_do_update(
            index_elements=[counter.c.day],
            set_={"last_number": counter.c.last_number + 1},
        )
        .returning(counter.c.last_number)
    )
    number = (await session.execute(stmt)).scalar_one()
    return f"PR-{day:%Y%m%d}-{number:03d}"


# --- Errors --------------------------------------------------------------------------------------


def _field_error(loc: list[str], type_: str, msg: str) -> dict[str, Any]:
    return {"loc": loc, "type": type_, "msg": msg}


def _invalid(fields: list[dict[str, Any]], message: str = "Invalid values") -> AppError:
    return AppError(422, ErrorCode.VALIDATION_ERROR, message, {"fields": fields})


def _not_ready() -> AppError:
    return AppError(
        409, ErrorCode.PRODUCTION_STEP_NOT_READY, "The previous step must be finished first"
    )


def _step_finished() -> AppError:
    return AppError(
        409, ErrorCode.PRODUCTION_STEP_FINISHED, "This step is finished; reopen it to edit"
    )


# --- Loading -------------------------------------------------------------------------------------


async def get_batch(
    session: AsyncSession, batch_id: uuid.UUID, *, lock: bool = False
) -> ProductionBatch:
    stmt = (
        select(ProductionBatch)
        .where(ProductionBatch.id == batch_id)
        .execution_options(populate_existing=True)
    )
    if lock:
        stmt = stmt.with_for_update()
    batch = await session.scalar(stmt)
    if batch is None:
        raise AppError(404, ErrorCode.PRODUCTION_NOT_FOUND, "Production batch not found")
    return batch


async def _for_write(session: AsyncSession, batch_id: uuid.UUID) -> ProductionBatch:
    batch = await get_batch(session, batch_id, lock=True)
    if batch.status == "cancelled":
        raise AppError(409, ErrorCode.PRODUCTION_CANCELLED, "This batch is cancelled")
    return batch


async def _check_version(session: AsyncSession, batch: ProductionBatch, version: int) -> None:
    if batch.version != version:
        current = await batch_out(session, batch)
        raise AppError(
            409,
            ErrorCode.PRODUCTION_CONFLICT,
            "Someone else changed this batch; reload and try again",
            {"batch": current.model_dump(mode="json")},
        )


def _step_row(batch: ProductionBatch, step: int) -> StepRow | None:
    return {1: batch.raw_material, 2: batch.output, 3: batch.packaging}[step]


def _kind(code: str) -> MaterialKindDef:
    return MATERIAL_KINDS_BY_CODE.get(code) or MATERIAL_KINDS_BY_CODE[DEFAULT_MATERIAL_KIND]


def _recompute_counts(batch: ProductionBatch) -> None:
    """Step 2 counts = quantity × pieces per unit. Called whenever either input may change."""
    if batch.output is None:
        return
    kind = _kind(batch.raw_material.material_kind)
    quantity = batch.raw_material.quantity or 0
    batch.output.wings_count = quantity * kind.wings_per_unit
    batch.output.thighs_count = quantity * kind.thighs_per_unit


def _ensure_byproducts(batch: ProductionBatch) -> dict[str, ProductionByproduct]:
    """One row per catalog item (a catalog entry added later gets its row on demand)."""
    rows = {b.item_code: b for b in batch.byproducts}
    for code in BYPRODUCT_CODES:
        if code not in rows:
            rows[code] = ProductionByproduct(item_code=code)
            batch.byproducts.append(rows[code])
    return rows


def _touch(batch: ProductionBatch, row: StepRow | None, actor: User) -> None:
    now = utcnow()
    if row is not None:
        row.updated_by = actor.id
        row.updated_at = now
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
        entity_type=ENTITY,
        entity_id=batch.id,
        details={"code": batch.code, **details},
    )


# --- Create and drafts ---------------------------------------------------------------------------


async def _apply_raw(
    session: AsyncSession, batch: ProductionBatch, data: RawMaterialFields, fields: set[str]
) -> None:
    raw = batch.raw_material
    errors: list[dict[str, Any]] = []
    if "production_date" in fields:
        if data.production_date is None:
            errors.append(_field_error(["body", "production_date"], "missing", "Date is required"))
        else:
            batch.production_date = data.production_date
    if "material_kind" in fields:
        if data.material_kind is None or data.material_kind not in MATERIAL_KINDS_BY_CODE:
            errors.append(
                _field_error(["body", "material_kind"], "value_error", "Unknown material kind")
            )
        else:
            raw.material_kind = data.material_kind
    if errors:
        raise _invalid(errors)
    if "supplier_id" in fields:
        if data.supplier_id is not None and await session.get(Supplier, data.supplier_id) is None:
            raise AppError(422, ErrorCode.SUPPLIER_NOT_FOUND, "Supplier not found")
        raw.supplier_id = data.supplier_id
    if "weight_kg" in fields:
        raw.weight_kg = data.weight_kg
    if "quantity" in fields:
        raw.quantity = data.quantity
    _recompute_counts(batch)


async def create_batch(
    session: AsyncSession, actor: User, data: ProductionCreate
) -> ProductionBatch:
    day = data.production_date or business_today()
    now = utcnow()
    batch = ProductionBatch(
        code=await next_code(session, day),
        production_date=day,
        created_by=actor.id,
        updated_by=actor.id,
        created_at=now,
        updated_at=now,
        # Explicit so nothing lazy-loads on a new object.
        output=None,
        packaging=None,
        byproducts=[],
        raw_material=ProductionRawMaterial(
            material_kind=DEFAULT_MATERIAL_KIND, updated_by=actor.id, updated_at=now
        ),
    )
    session.add(batch)
    await _apply_raw(session, batch, data, set(data.model_fields_set) - {"production_date"})
    await session.flush()
    _audit(session, "production.create", actor, batch)
    await session.commit()
    return await get_batch(session, batch.id)


async def save_raw_material(
    session: AsyncSession, actor: User, batch_id: uuid.UUID, data: RawMaterialFields, version: int
) -> ProductionBatch:
    batch = await _for_write(session, batch_id)
    if batch.raw_material.finished:
        raise _step_finished()
    await _check_version(session, batch, version)
    await _apply_raw(session, batch, data, set(data.model_fields_set) - {"version"})
    _touch(batch, batch.raw_material, actor)
    await session.commit()
    return await get_batch(session, batch_id)


def _unknown_byproducts(codes: set[str]) -> None:
    unknown = sorted(codes - set(BYPRODUCTS_BY_CODE))
    if unknown:
        raise _invalid(
            [
                _field_error(["body", "byproducts", c], "value_error", "Unknown by-product")
                for c in unknown
            ]
        )


async def save_produced(
    session: AsyncSession, actor: User, batch_id: uuid.UUID, data: ProducedDraft
) -> ProductionBatch:
    batch = await _for_write(session, batch_id)
    output = batch.output
    if output is None or not batch.raw_material.finished:
        raise _not_ready()
    if output.finished:
        raise _step_finished()
    await _check_version(session, batch, data.version)
    fields = data.model_fields_set
    if data.byproducts:
        _unknown_byproducts(set(data.byproducts))
    for attr in ("wings_kg", "thighs_kg", "marinade_g"):
        if attr in fields:
            setattr(output, attr, getattr(data, attr))
    if data.byproducts:
        rows = _ensure_byproducts(batch)
        for code, kg in data.byproducts.items():
            rows[code].produced_kg = kg
    _recompute_counts(batch)
    _touch(batch, output, actor)
    await session.commit()
    return await get_batch(session, batch_id)


async def save_standardize(
    session: AsyncSession, actor: User, batch_id: uuid.UUID, data: StandardizeDraft
) -> ProductionBatch:
    batch = await _for_write(session, batch_id)
    packaging = batch.packaging
    if packaging is None or batch.output is None or not batch.output.finished:
        raise _not_ready()
    if packaging.finished:
        raise _step_finished()
    await _check_version(session, batch, data.version)
    fields = data.model_fields_set
    if data.byproducts:
        _unknown_byproducts(set(data.byproducts))
    for attr in ("big_packages", "small_packages", "rejected_wings", "rejected_thighs"):
        if attr in fields:
            setattr(packaging, attr, getattr(data, attr))
    if "comment" in fields:
        comment = (data.comment or "").strip()
        packaging.comment = comment or None
    if data.byproducts:
        rows = _ensure_byproducts(batch)
        for code, disposition in data.byproducts.items():
            for attr in disposition.model_fields_set:
                setattr(rows[code], attr, getattr(disposition, attr))
    _touch(batch, packaging, actor)
    await session.commit()
    return await get_batch(session, batch_id)


# --- Finish --------------------------------------------------------------------------------------


def _require(errors: list, loc: list[str], value: Any, *, positive: bool = False) -> None:
    if value is None:
        errors.append(_field_error(loc, "missing", "Required"))
    elif positive and value <= 0:
        errors.append(_field_error(loc, "greater_than", "Must be greater than 0"))


async def _validate_raw(session: AsyncSession, batch: ProductionBatch) -> None:
    raw = batch.raw_material
    errors: list[dict[str, Any]] = []
    _require(errors, ["raw_material", "supplier_id"], raw.supplier_id)
    _require(errors, ["raw_material", "weight_kg"], raw.weight_kg, positive=True)
    _require(errors, ["raw_material", "quantity"], raw.quantity, positive=True)
    if raw.material_kind not in MATERIAL_KINDS_BY_CODE:
        errors.append(
            _field_error(["raw_material", "material_kind"], "value_error", "Unknown material kind")
        )
    if errors:
        raise _invalid(errors, "Step 1 is incomplete")
    supplier = await session.get(Supplier, raw.supplier_id)
    if supplier is None or not supplier.is_active:
        raise AppError(
            422, ErrorCode.SUPPLIER_INACTIVE, "The supplier is deactivated; choose another one"
        )


def _validate_produced(batch: ProductionBatch) -> None:
    output = batch.output
    assert output is not None
    errors: list[dict[str, Any]] = []
    _require(errors, ["produced", "wings_kg"], output.wings_kg, positive=True)
    _require(errors, ["produced", "thighs_kg"], output.thighs_kg, positive=True)
    _require(errors, ["produced", "marinade_g"], output.marinade_g)
    rows = _ensure_byproducts(batch)
    for code in BYPRODUCT_CODES:
        _require(errors, ["produced", "byproducts", code], rows[code].produced_kg)
    if errors:
        raise _invalid(errors, "Step 2 is incomplete")


def _validate_standardize(batch: ProductionBatch) -> None:
    output, packaging = batch.output, batch.packaging
    assert output is not None and packaging is not None
    errors: list[dict[str, Any]] = []
    for attr in ("big_packages", "small_packages", "rejected_wings", "rejected_thighs"):
        _require(errors, ["standardize", attr], getattr(packaging, attr))
    rows = _ensure_byproducts(batch)
    for code in BYPRODUCT_CODES:
        for attr in ("carry_kg", "rejected_kg"):
            _require(errors, ["standardize", "byproducts", code, attr], getattr(rows[code], attr))
    if errors:
        raise _invalid(errors, "Step 3 is incomplete")

    # Pieces must add up exactly. (By-product kg balance is UI-only: not checked here.)
    packed = 2 * packaging.big_packages + packaging.small_packages
    balance = {
        "wings": (output.wings_count, packed + packaging.rejected_wings),
        "thighs": (output.thighs_count, packed + packaging.rejected_thighs),
    }
    if any(expected != assigned for expected, assigned in balance.values()):
        raise AppError(
            422,
            ErrorCode.PRODUCTION_BALANCE_MISMATCH,
            "Packed and rejected pieces must equal the produced pieces",
            {
                piece: {"expected": e, "assigned": a, "difference": e - a}
                for piece, (e, a) in balance.items()
            },
        )


async def finish_step(
    session: AsyncSession, actor: User, batch_id: uuid.UUID, step: int, version: int
) -> ProductionBatch:
    batch = await _for_write(session, batch_id)
    row = _step_row(batch, step)
    previous = _step_row(batch, step - 1) if step > 1 else None
    if row is None or (previous is not None and not previous.finished):
        raise _not_ready()
    if row.finished:
        raise _step_finished()
    await _check_version(session, batch, version)

    if step == 1:
        await _validate_raw(session, batch)
    elif step == 2:
        _recompute_counts(batch)
        _validate_produced(batch)
    else:
        _validate_standardize(batch)

    now = utcnow()
    row.status = "finished"
    row.finished_by = actor.id
    row.finished_at = now
    if step == 1:
        if batch.output is None:
            batch.output = ProductionOutput(updated_by=actor.id, updated_at=now)
        _ensure_byproducts(batch)
        _recompute_counts(batch)
        batch.current_step = 2
    elif step == 2:
        if batch.packaging is None:
            batch.packaging = ProductionPackaging(updated_by=actor.id, updated_at=now)
        batch.current_step = 3
    else:
        batch.status = "completed"
        batch.completed_at = now
    _touch(batch, row, actor)
    _audit(session, "production.step_finish", actor, batch, step=step)
    await session.commit()
    return await get_batch(session, batch_id)


# --- Reopen and cancel ---------------------------------------------------------------------------


async def reopen_step(
    session: AsyncSession, actor: User, batch_id: uuid.UUID, step: int, version: int
) -> ProductionBatch:
    batch = await _for_write(session, batch_id)
    row = _step_row(batch, step)
    if row is None or not row.finished:
        # Nothing to reopen: already editable (or not started).
        return batch
    following = _step_row(batch, step + 1) if step < 3 else None
    if following is not None and following.finished:
        raise AppError(
            409,
            ErrorCode.PRODUCTION_STEP_LOCKED,
            "Reopen the next step first: it is already finished",
        )
    await _check_version(session, batch, version)
    row.status = "draft"
    row.finished_by = None
    row.finished_at = None
    batch.current_step = step
    if batch.status == "completed":
        batch.status = "in_progress"
        batch.completed_at = None
    _touch(batch, row, actor)
    _audit(session, "production.step_reopen", actor, batch, step=step)
    await session.commit()
    return await get_batch(session, batch_id)


async def cancel_batch(
    session: AsyncSession, actor: User, batch_id: uuid.UUID, reason: str, version: int
) -> ProductionBatch:
    batch = await _for_write(session, batch_id)
    if batch.status == "completed":
        raise AppError(409, ErrorCode.PRODUCTION_COMPLETED, "Completed batches can't be cancelled")
    await _check_version(session, batch, version)
    now = utcnow()
    batch.status = "cancelled"
    batch.cancel_reason = reason
    batch.cancelled_by = actor.id
    batch.cancelled_at = now
    _touch(batch, None, actor)
    _audit(session, "production.cancel", actor, batch, reason=reason)
    await session.commit()
    return await get_batch(session, batch_id)


# --- Reading -------------------------------------------------------------------------------------


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


async def list_batches(
    session: AsyncSession,
    *,
    status: ListStatus,
    waiting_step: int | None,
    date_from: date | None,
    date_to: date | None,
    q: str | None,
    sort: ProductionSort,
    page: int,
    page_size: int,
) -> tuple[list[ProductionBatch], int]:
    b, r, s = ProductionBatch, ProductionRawMaterial, Supplier
    conditions: list[Any] = []
    if status != "all":
        conditions.append(b.status == status)
    if waiting_step is not None:
        # current_step == N on an in-progress batch: steps before N are finished, N is not.
        conditions += [b.status == "in_progress", b.current_step == waiting_step]
    if date_from:
        conditions.append(b.production_date >= date_from)
    if date_to:
        conditions.append(b.production_date <= date_to)
    if q and q.strip():
        pattern = f"%{_escape_like(q.strip())}%"
        conditions.append(
            or_(b.code.ilike(pattern, escape="\\"), s.name.ilike(pattern, escape="\\"))
        )

    def _from(stmt):
        return stmt.join(r, r.batch_id == b.id).outerjoin(s, s.id == r.supplier_id)

    order = {
        "date": [b.production_date.asc(), b.code.asc()],
        "-date": [b.production_date.desc(), b.code.desc()],
        "code": [b.code.asc()],
        "-code": [b.code.desc()],
    }[sort]
    total = await session.scalar(_from(select(func.count(b.id))).where(*conditions)) or 0
    items = await session.scalars(
        _from(select(b))
        .where(*conditions)
        .order_by(*order, b.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return list(items), total


async def stats(session: AsyncSession) -> ProductionStats:
    b, r, p = ProductionBatch, ProductionRawMaterial, ProductionPackaging
    today = business_today()
    month_start = today.replace(day=1)
    next_month = (month_start + timedelta(days=32)).replace(day=1)
    in_month = [
        b.status != "cancelled",
        b.production_date >= month_start,
        b.production_date < next_month,
    ]
    in_progress = await session.scalar(select(func.count(b.id)).where(b.status == "in_progress"))
    completed_today = await session.scalar(
        select(func.count(b.id)).where(
            b.status == "completed",
            b.completed_at >= _local_midnight(today),
            b.completed_at < _local_midnight(today + timedelta(days=1)),
        )
    )
    chickens = await session.scalar(
        select(func.coalesce(func.sum(r.quantity), 0))
        .join(b, b.id == r.batch_id)
        .where(r.status == "finished", *in_month)
    )
    rejected = await session.scalar(
        select(func.coalesce(func.sum(p.rejected_wings + p.rejected_thighs), 0))
        .join(b, b.id == p.batch_id)
        .where(p.status == "finished", *in_month)
    )
    return ProductionStats(
        in_progress=in_progress or 0,
        completed_today=completed_today or 0,
        chickens_this_month=chickens or 0,
        rejected_pieces_this_month=rejected or 0,
    )


async def supplier_options(session: AsyncSession, q: str | None) -> list[SupplierOption]:
    conditions: list[Any] = [Supplier.is_active]
    if q and q.strip():
        term = q.strip()
        matches = [Supplier.name.ilike(f"%{_escape_like(term)}%", escape="\\")]
        digits = _NON_DIGITS.sub("", term)
        if digits:
            matches.append(Supplier.phone.contains(digits, autoescape=True))
        conditions.append(or_(*matches))
    rows = await session.scalars(
        select(Supplier)
        .where(*conditions)
        .order_by(func.lower(Supplier.name), Supplier.id)
        .limit(SUPPLIER_OPTIONS_LIMIT)
    )
    return [SupplierOption(id=s.id, name=s.name, phone_display=format_phone(s.phone)) for s in rows]


# --- Serialization -------------------------------------------------------------------------------


def _user_ids(batch: ProductionBatch) -> set[uuid.UUID]:
    ids = {batch.created_by, batch.updated_by, batch.cancelled_by}
    for row in (batch.raw_material, batch.output, batch.packaging):
        if row is not None:
            ids |= {row.finished_by, row.updated_by}
    return {i for i in ids if i is not None}


async def _users(session: AsyncSession, ids: set[uuid.UUID]) -> dict[uuid.UUID, User]:
    if not ids:
        return {}
    return {u.id: u for u in await session.scalars(select(User).where(User.id.in_(ids)))}


async def _suppliers(session: AsyncSession, ids: set[uuid.UUID]) -> dict[uuid.UUID, Supplier]:
    if not ids:
        return {}
    return {s.id: s for s in await session.scalars(select(Supplier).where(Supplier.id.in_(ids)))}


def _ref(users: dict[uuid.UUID, User], user_id: uuid.UUID | None) -> UserRef | None:
    user = users.get(user_id) if user_id else None
    return UserRef.model_validate(user) if user else None


def _brief(supplier: Supplier | None) -> SupplierBrief | None:
    if supplier is None:
        return None
    return SupplierBrief(
        id=supplier.id,
        name=supplier.name,
        phone_display=format_phone(supplier.phone),
        is_active=supplier.is_active,
    )


def _step_common(row: StepRow, users: dict[uuid.UUID, User]) -> dict[str, Any]:
    return {
        "status": row.status,
        "finished_by": _ref(users, row.finished_by),
        "finished_at": row.finished_at,
        "updated_by": _ref(users, row.updated_by),
        "updated_at": row.updated_at,
    }


def computed(batch: ProductionBatch) -> ComputedOut:
    raw, output = batch.raw_material, batch.output
    kind = _kind(raw.material_kind)
    quantity = raw.quantity or 0
    yield_percent = None
    if (
        output is not None
        and output.wings_kg is not None
        and output.thighs_kg is not None
        and raw.weight_kg
    ):
        ratio = (output.wings_kg + output.thighs_kg) / raw.weight_kg * 100
        yield_percent = str(ratio.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))
    return ComputedOut(
        wings_count=quantity * kind.wings_per_unit,
        thighs_count=quantity * kind.thighs_per_unit,
        yield_percent=yield_percent,
    )


CATALOG = CatalogOut(
    byproducts=[
        ByproductCatalogOut(
            code=b.code, name_en=b.name_en, name_km=b.name_km, unit=b.unit, order=b.order
        )
        for b in sorted(BYPRODUCTS, key=lambda b: b.order)
    ],
    material_kinds=[
        MaterialKindCatalogOut(
            code=k.code,
            name_en=k.name_en,
            name_km=k.name_km,
            wings_per_unit=k.wings_per_unit,
            thighs_per_unit=k.thighs_per_unit,
        )
        for k in MATERIAL_KINDS
    ],
)


async def batch_out(session: AsyncSession, batch: ProductionBatch) -> BatchOut:
    users = await _users(session, _user_ids(batch))
    raw, output, packaging = batch.raw_material, batch.output, batch.packaging
    supplier = await session.get(Supplier, raw.supplier_id) if raw.supplier_id else None
    order = {code: i for i, code in enumerate(BYPRODUCT_CODES)}
    byproducts = sorted(
        batch.byproducts, key=lambda b: (order.get(b.item_code, len(order)), b.item_code)
    )
    return BatchOut(
        id=batch.id,
        code=batch.code,
        production_date=batch.production_date,
        status=batch.status,
        current_step=batch.current_step,
        version=batch.version,
        cancel_reason=batch.cancel_reason,
        created_at=batch.created_at,
        updated_at=batch.updated_at,
        completed_at=batch.completed_at,
        cancelled_at=batch.cancelled_at,
        created_by=_ref(users, batch.created_by),
        updated_by=_ref(users, batch.updated_by),
        cancelled_by=_ref(users, batch.cancelled_by),
        raw_material=RawMaterialOut(
            **_step_common(raw, users),
            supplier=_brief(supplier),
            material_kind=raw.material_kind,
            weight_kg=raw.weight_kg,
            quantity=raw.quantity,
        ),
        produced=None
        if output is None
        else ProducedOut(
            **_step_common(output, users),
            wings_kg=output.wings_kg,
            thighs_kg=output.thighs_kg,
            wings_count=output.wings_count,
            thighs_count=output.thighs_count,
            marinade_g=output.marinade_g,
        ),
        standardize=None
        if packaging is None
        else StandardizeOut(
            **_step_common(packaging, users),
            big_packages=packaging.big_packages,
            small_packages=packaging.small_packages,
            rejected_wings=packaging.rejected_wings,
            rejected_thighs=packaging.rejected_thighs,
            comment=packaging.comment,
        ),
        byproducts=[
            ByproductOut(
                item_code=b.item_code,
                produced_kg=b.produced_kg,
                carry_kg=b.carry_kg,
                rejected_kg=b.rejected_kg,
            )
            for b in byproducts
        ],
        computed=computed(batch),
        catalog=CATALOG,
    )


async def list_items(session: AsyncSession, batches: list[ProductionBatch]) -> list[BatchListItem]:
    users = await _users(session, {b.created_by for b in batches if b.created_by})
    suppliers = await _suppliers(
        session, {b.raw_material.supplier_id for b in batches if b.raw_material.supplier_id}
    )

    def _status(row: StepRow | None) -> str:
        return "pending" if row is None else row.status

    return [
        BatchListItem(
            id=b.id,
            code=b.code,
            production_date=b.production_date,
            status=b.status,
            current_step=b.current_step,
            steps=[_status(b.raw_material), _status(b.output), _status(b.packaging)],
            supplier=_brief(suppliers.get(b.raw_material.supplier_id))
            if b.raw_material.supplier_id
            else None,
            material_kind=b.raw_material.material_kind,
            quantity=b.raw_material.quantity,
            created_by=_ref(users, b.created_by),
            updated_at=b.updated_at,
        )
        for b in batches
    ]
