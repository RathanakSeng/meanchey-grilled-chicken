"""Preparations: raw materials made ready to use (satay sachets, prepared packaging materials).

Not production step 3 (Standardize): a preparation only converts materials.

- **Types:** `satay_sachet` (one line per pack size, 2 and / or 4: satay sauce used in g, zip bags
  7 used in that material's unit, sachets made; all typed in, no recipe) and
  `packaging_material` (one line per material with `prep_role = packaging` and a quantity: the
  same quantity moves 1:1 from the material to its prepared twin, `<item_code>_prepared`).
- **Drafts** (`preparation.create`): partial values; only types, >= 0, the unit's precision and
  the line kind are checked. Every write locks the row (`FOR UPDATE`) and uses `version`
  (stale → `409 PREPARATION_CONFLICT` with the current preparation). Checks run in this order:
  not found, cancelled (PREPARATION_CANCELLED), status (PREPARATION_INVALID_STATUS), version,
  values.
- **Finish** (`preparation.create`): >= 1 line, every value present and > 0, materials active
  (MATERIAL_ARCHIVED) and with the right `prep_role` (VALIDATION_ERROR), then in one
  transaction the movements (`source = preparation`, `preparation_id`), through
  `inventory_service.apply_movements` (not enough stock → INVENTORY_INSUFFICIENT, nothing
  changes):
  - satay line: −satay sauce (g, converted when the material is in kg), −zip bag 7 (2 or 4),
    +satay sachets (2 or 4);
  - packaging line: −material, +its prepared twin (same quantity and unit).
  `prepared_date` = today in BUSINESS_TIMEZONE; the managers' alert is stored in the same
  transaction (holders of `preparation.update`; Telegram after the commit).
- **Reopen** (`preparation.update`): finished → draft, values kept, its movements reversed
  (blocked by INVENTORY_INSUFFICIENT when the outputs are no longer in stock), date cleared.
- **Cancel** (`preparation.cancel`, reason): a draft is just cancelled; a finished one is
  reversed first. Cancelled is read-only.
- Line quantities are stored in `unit`, the material's unit when the line was saved: a later
  kg <-> g switch is converted at Finish; a switch to / from count needs the line re-entered.
- Audit (`entity_type = preparation`, `details.code`): `preparation.create`,
  `preparation.finish`, `preparation.reopen`, `preparation.cancel`. Draft saves aren't audited.
"""

import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import Date, and_, cast, exists, func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.config import get_settings
from app.core.errors import AppError, ErrorCode
from app.inventory import units
from app.inventory.catalog import ITEMS_BY_CODE, SATAY_SACHETS, prepared_code
from app.models import (
    InventoryBalance,
    InventoryMaterial,
    InventoryMovement,
    Preparation,
    PreparationCounter,
    PreparationLine,
    User,
    utcnow,
)
from app.schemas.common import UserRef
from app.schemas.preparation import (
    PreparationCreate,
    PreparationDraft,
    PreparationItemOut,
    PreparationLineIn,
    PreparationLineOut,
    PreparationListItem,
    PreparationListStatus,
    PreparationMaterialOut,
    PreparationOut,
    PreparationStats,
    PreparationType,
    SatayMaterialsOut,
)
from app.services import inventory_service, notification_service
from app.services.audit_service import record
from app.services.inventory_service import Delta

ENTITY = "preparation"
SATAY = "satay_sachet"
PACKAGING = "packaging_material"
SATAY_SAUCE = "satay_sauce"
ZIP_BAG_ROLES: dict[int, str] = {2: "zip_bag_2", 4: "zip_bag_4"}
SATAY_ROLES = (SATAY_SAUCE, *ZIP_BAG_ROLES.values())
SATAY_FIELDS = ("pack_size", "satay_g", "zip_bag_qty", "sachets")
PACKAGING_FIELDS = ("material_id", "quantity")


# --- Calendar and codes --------------------------------------------------------------------------


def business_today(now: datetime | None = None) -> date:
    return (now or utcnow()).astimezone(get_settings().business_tz).date()


def _creation_day():
    """SQL: the preparation's creation day in BUSINESS_TIMEZONE."""
    return cast(func.timezone(get_settings().business_timezone, Preparation.created_at), Date)


async def next_code(session: AsyncSession, day: date) -> str:
    """PP-YYYYMMDD-NNN. The counter row stays locked until the transaction ends, so concurrent
    creations on the same day get distinct numbers."""
    counter = PreparationCounter.__table__
    stmt = (
        pg_insert(counter)
        .values(day=day, last_number=1)
        .on_conflict_do_update(
            index_elements=[counter.c.day], set_={"last_number": counter.c.last_number + 1}
        )
        .returning(counter.c.last_number)
    )
    number = (await session.execute(stmt)).scalar_one()
    return f"PP-{day:%Y%m%d}-{number:03d}"


# --- Errors --------------------------------------------------------------------------------------


def _field(loc: list[Any], msg: str, type_: str = "value_error") -> dict[str, Any]:
    return {"loc": [str(part) for part in loc], "type": type_, "msg": msg}


def _invalid(fields: list[dict[str, Any]], message: str = "Invalid values") -> AppError:
    return AppError(422, ErrorCode.VALIDATION_ERROR, message, {"fields": fields})


def _invalid_status(p: Preparation) -> AppError:
    return AppError(
        409,
        ErrorCode.PREPARATION_INVALID_STATUS,
        "This action isn't allowed in the preparation's status",
        {"status": p.status},
    )


def _archived(m: InventoryMaterial) -> AppError:
    return AppError(
        409,
        ErrorCode.MATERIAL_ARCHIVED,
        "This material is archived; restore it first",
        {"material_id": str(m.id), "name_en": m.name_en, "name_km": m.name_km},
    )


# --- Loading -------------------------------------------------------------------------------------


async def get_preparation(
    session: AsyncSession, preparation_id: uuid.UUID, *, lock: bool = False
) -> Preparation:
    stmt = (
        select(Preparation)
        .where(Preparation.id == preparation_id)
        .execution_options(populate_existing=True)
    )
    if lock:
        stmt = stmt.with_for_update()
    p = await session.scalar(stmt)
    if p is None:
        raise AppError(404, ErrorCode.PREPARATION_NOT_FOUND, "Preparation not found")
    return p


async def _for_write(session: AsyncSession, preparation_id: uuid.UUID) -> Preparation:
    p = await get_preparation(session, preparation_id, lock=True)
    if p.status == "cancelled":
        raise AppError(409, ErrorCode.PREPARATION_CANCELLED, "This preparation is cancelled")
    return p


async def _check_version(session: AsyncSession, p: Preparation, version: int) -> None:
    if p.version != version:
        current = await preparation_out(session, p)
        raise AppError(
            409,
            ErrorCode.PREPARATION_CONFLICT,
            "Someone else changed this preparation; reload and try again",
            {"preparation": current.model_dump(mode="json")},
        )


async def _role_materials(
    session: AsyncSession, *, lock: bool = False
) -> dict[str, InventoryMaterial]:
    """The satay sachet inputs by role (archived included). `lock`: a share lock, so a unit
    change of one of them waits for the Finish."""
    stmt = select(InventoryMaterial).where(InventoryMaterial.prep_role.in_(SATAY_ROLES))
    if lock:
        stmt = stmt.with_for_update(read=True)
    rows = await session.scalars(stmt.execution_options(populate_existing=True))
    return {m.prep_role: m for m in rows}


async def _materials(
    session: AsyncSession, ids: set[uuid.UUID], *, lock: bool = False
) -> dict[uuid.UUID, InventoryMaterial]:
    if not ids:
        return {}
    stmt = select(InventoryMaterial).where(InventoryMaterial.id.in_(ids))
    if lock:
        stmt = stmt.with_for_update(read=True)
    return {m.id: m for m in await session.scalars(stmt.execution_options(populate_existing=True))}


def _touch(p: Preparation, actor: User) -> None:
    p.updated_by = actor.id
    p.updated_at = utcnow()
    p.version += 1


def _audit(session: AsyncSession, action: str, actor: User, p: Preparation, **details: Any) -> None:
    record(
        session,
        action,
        actor_id=actor.id,
        entity_type=ENTITY,
        entity_id=p.id,
        details={"code": p.code, "type": p.type, **details},
    )


# --- Create and drafts ---------------------------------------------------------------------------


async def create_preparation(
    session: AsyncSession, actor: User, data: PreparationCreate
) -> Preparation:
    now = utcnow()
    p = Preparation(
        code=await next_code(session, business_today(now)),
        type=data.type,
        status="draft",
        created_by=actor.id,
        updated_by=actor.id,
        created_at=now,
        updated_at=now,
        lines=[],
    )
    session.add(p)
    await session.flush()
    _audit(session, "preparation.create", actor, p)
    await session.commit()
    return await get_preparation(session, p.id)


def _precision_error(unit: str) -> str:
    return {
        "count": "Whole numbers only",
        "kg": "At most 3 decimals",
        "g": "At most 1 decimal",
    }[unit]


def _check_quantity(
    errors: list, loc: list[Any], unit: str | None, value: Decimal | None
) -> Decimal | None:
    if value is None:
        return None
    if unit is not None:
        if not units.has_precision(unit, value):  # type: ignore[arg-type]
            errors.append(_field(loc, _precision_error(unit)))
            return None
        if value > units.MAX_QUANTITY[unit]:  # type: ignore[index]
            errors.append(_field(loc, "The quantity is too large"))
            return None
        return units.quantize(unit, value)  # type: ignore[arg-type]
    return value


async def _apply_lines(
    session: AsyncSession, p: Preparation, lines: list[PreparationLineIn]
) -> None:
    """Replace the lines (matched by pack size / material, so unique keys never collide)."""
    errors: list[dict[str, Any]] = []
    wanted: list[dict[str, Any]] = []
    if p.type == SATAY:
        roles = await _role_materials(session)
        seen: set[int] = set()
        for i, line in enumerate(lines):
            loc = ["body", "lines", i]
            for name in PACKAGING_FIELDS:
                if getattr(line, name) is not None:
                    errors.append(_field([*loc, name], "Not a field of satay sachet lines"))
            if line.pack_size is None:
                errors.append(_field([*loc, "pack_size"], "Field required", "missing"))
                continue
            if line.pack_size in seen:
                errors.append(_field([*loc, "pack_size"], "One line per pack size"))
                continue
            seen.add(line.pack_size)
            zip_bag = roles.get(ZIP_BAG_ROLES[line.pack_size])
            unit = zip_bag.unit if zip_bag is not None else None
            wanted.append(
                {
                    "key": ("pack", line.pack_size),
                    "pack_size": line.pack_size,
                    "satay_g": line.satay_g,
                    "quantity": _check_quantity(
                        errors, [*loc, "zip_bag_qty"], unit, line.zip_bag_qty
                    ),
                    "unit": unit,
                    "sachets": line.sachets,
                    "material_id": None,
                }
            )
    else:
        materials = await _materials(
            session, {line.material_id for line in lines if line.material_id is not None}
        )
        seen_ids: set[uuid.UUID] = set()
        for i, line in enumerate(lines):
            loc = ["body", "lines", i]
            for name in SATAY_FIELDS:
                if getattr(line, name) is not None:
                    errors.append(_field([*loc, name], "Not a field of packaging material lines"))
            if line.material_id is None:
                errors.append(_field([*loc, "material_id"], "Field required", "missing"))
                continue
            m = materials.get(line.material_id)
            if m is None:
                errors.append(_field([*loc, "material_id"], "Unknown material"))
                continue
            if m.prep_role != "packaging":
                errors.append(_field([*loc, "material_id"], "This material can't be prepared"))
                continue
            if m.id in seen_ids:
                errors.append(_field([*loc, "material_id"], "One line per material"))
                continue
            seen_ids.add(m.id)
            wanted.append(
                {
                    "key": ("material", m.id),
                    "pack_size": None,
                    "satay_g": None,
                    "quantity": _check_quantity(errors, [*loc, "quantity"], m.unit, line.quantity),
                    "unit": m.unit,
                    "sachets": None,
                    "material_id": m.id,
                }
            )
    if errors:
        raise _invalid(errors)

    def key(row: PreparationLine) -> tuple:
        return (
            ("pack", row.pack_size) if row.pack_size is not None else ("material", row.material_id)
        )

    existing = {key(row): row for row in p.lines}
    new_rows = []
    for position, values in enumerate(wanted, start=1):
        row = existing.pop(values.pop("key"), None) or PreparationLine()
        for name, value in values.items():
            setattr(row, name, value)
        row.position = position
        new_rows.append(row)
    p.lines[:] = new_rows


async def save_draft(
    session: AsyncSession, actor: User, preparation_id: uuid.UUID, data: PreparationDraft
) -> Preparation:
    p = await _for_write(session, preparation_id)
    if p.status != "draft":
        raise _invalid_status(p)
    await _check_version(session, p, data.version)
    fields = data.model_fields_set
    if "lines" in fields:
        await _apply_lines(session, p, data.lines or [])
    if "note" in fields:
        p.note = (data.note or "").strip() or None
    _touch(p, actor)
    await session.commit()
    return await get_preparation(session, p.id)


# --- Finish --------------------------------------------------------------------------------------


@dataclass
class _Plan:
    deltas: list[Delta]
    summary: dict[str, Any]


def _amount_delta(m: InventoryMaterial, signed: Decimal, code: str | None = None) -> Delta:
    """A movement of `signed` (in the material's unit) on the material, or its twin (`code`)."""
    return Delta(
        code or m.item_code,
        count=int(signed) if m.unit == "count" else None,
        kg=signed if m.unit == "kg" else None,
        g=signed if m.unit == "g" else None,
    )


def _in_unit(
    errors: list, loc: list[Any], m: InventoryMaterial, qty: Decimal, unit: str | None
) -> Decimal | None:
    """A line quantity (saved in `unit`) in the material's current unit."""
    if unit is None or unit == m.unit:
        if not units.has_precision(m.unit, qty):  # type: ignore[arg-type]
            errors.append(_field(loc, _precision_error(m.unit)))
            return None
        return qty
    if units.same_measure(unit, m.unit):  # type: ignore[arg-type]
        return units.convert(qty, unit, m.unit)  # type: ignore[arg-type]
    errors.append(_field(loc, "The material's unit changed; enter the quantity again"))
    return None


def _require(errors: list, loc: list[Any], value: Any) -> None:
    if value is None:
        errors.append(_field(loc, "Field required", "missing"))
    elif value <= 0:
        errors.append(_field(loc, "Must be more than 0", "greater_than"))


async def _finish_plan(session: AsyncSession, p: Preparation) -> _Plan:
    """Validate strictly and work out the movements (and the alert's summary)."""
    errors: list[dict[str, Any]] = []
    if not p.lines:
        raise _invalid([_field(["body", "lines"], "Add at least one line", "missing")])
    deltas: list[Delta] = []
    summary: dict[str, Any] = {"sachets_2": None, "sachets_4": None, "materials": []}
    if p.type == SATAY:
        roles = await _role_materials(session, lock=True)
        for i, line in enumerate(p.lines):
            loc = ["lines", i]
            _require(errors, [*loc, "satay_g"], line.satay_g)
            _require(errors, [*loc, "zip_bag_qty"], line.quantity)
            _require(errors, [*loc, "sachets"], line.sachets)
            sauce = roles.get(SATAY_SAUCE)
            zip_bag = roles.get(ZIP_BAG_ROLES[line.pack_size or 2])
            for field, m in (("satay_g", sauce), ("zip_bag_qty", zip_bag)):
                if m is None:
                    errors.append(_field([*loc, field], "No material is set up for this input"))
                elif m.archived_at is not None:
                    raise _archived(m)
            if errors or sauce is None or zip_bag is None:
                continue
            assert line.satay_g is not None and line.quantity is not None and line.sachets
            if sauce.unit == "count":
                errors.append(_field([*loc, "satay_g"], "The satay sauce isn't measured by weight"))
                continue
            zip_qty = _in_unit(errors, [*loc, "zip_bag_qty"], zip_bag, line.quantity, line.unit)
            if zip_qty is None:
                continue
            deltas += [
                _amount_delta(sauce, -units.convert(line.satay_g, "g", sauce.unit)),  # type: ignore[arg-type]
                _amount_delta(zip_bag, -zip_qty),
                Delta(SATAY_SACHETS[line.pack_size or 2], count=line.sachets),
            ]
            summary[f"sachets_{line.pack_size}"] = line.sachets
    else:
        materials = await _materials(
            session, {line.material_id for line in p.lines if line.material_id}, lock=True
        )
        for i, line in enumerate(p.lines):
            loc = ["lines", i]
            _require(errors, [*loc, "quantity"], line.quantity)
            m = materials.get(line.material_id) if line.material_id else None
            if m is None:
                continue
            if m.archived_at is not None:
                raise _archived(m)
            if m.prep_role != "packaging":
                errors.append(_field([*loc, "material_id"], "This material can't be prepared"))
                continue
            if line.quantity is None or line.quantity <= 0:
                continue
            qty = _in_unit(errors, [*loc, "quantity"], m, line.quantity, line.unit)
            if qty is None:
                continue
            deltas += [_amount_delta(m, -qty), _amount_delta(m, qty, prepared_code(m.item_code))]
            summary["materials"].append(
                {
                    "name_en": m.name_en,
                    "name_km": m.name_km,
                    "quantity": str(units.quantize(m.unit, qty)),  # type: ignore[arg-type]
                    "unit": m.unit,
                }
            )
    if errors:
        raise _invalid(errors)
    return _Plan(deltas, summary)


async def finish(
    session: AsyncSession, actor: User, preparation_id: uuid.UUID, version: int
) -> Preparation:
    p = await _for_write(session, preparation_id)
    if p.status != "draft":
        raise _invalid_status(p)
    await _check_version(session, p, version)
    plan = await _finish_plan(session, p)
    await inventory_service.apply_movements(
        session, actor, plan.deltas, source="preparation", preparation_id=p.id
    )
    now = utcnow()
    p.status = "finished"
    p.prepared_date = business_today(now)
    p.finished_by = actor.id
    p.finished_at = now
    _touch(p, actor)
    _audit(session, "preparation.finish", actor, p, **plan.summary)
    await notification_service.notify(
        session,
        notification_service.PREPARATION_FINISHED,
        entity_type=ENTITY,
        entity_id=p.id,
        payload={"code": p.code, "type": p.type, **plan.summary, "actor_id": str(actor.id)},
        permission=notification_service.PREPARATION_ALERT_PERMISSION,
    )
    await session.commit()
    return await get_preparation(session, p.id)


# --- Reopen and cancel ---------------------------------------------------------------------------


async def _reverse(session: AsyncSession, actor: User, p: Preparation, cause: str) -> None:
    """Undo the preparation's open movements, each in its item's current unit. Not enough stock
    of an output any more → INVENTORY_INSUFFICIENT (nothing changes)."""
    reversal = aliased(InventoryMovement)
    originals = list(
        await session.scalars(
            select(InventoryMovement)
            .where(
                InventoryMovement.preparation_id == p.id,
                InventoryMovement.source == "preparation",
                InventoryMovement.reversal_of.is_(None),
                ~exists().where(reversal.reversal_of == InventoryMovement.id),
            )
            .order_by(InventoryMovement.id.desc())
        )
    )
    codes = {m.item_code for m in originals}
    materials = await inventory_service.materials_by_code(session, codes)
    materials.update(await inventory_service.twin_materials(session, codes))
    deltas = [
        inventory_service._in_current_unit(
            Delta(
                m.item_code,
                -m.count_delta if m.count_delta is not None else None,
                -m.kg_delta if m.kg_delta is not None else None,
                -m.g_delta if m.g_delta is not None else None,
                reversal_of=m.id,
                reason=cause,
            ),
            materials.get(m.item_code),
        )
        for m in originals
    ]
    await inventory_service.apply_movements(
        session, actor, deltas, source="preparation", preparation_id=p.id
    )


async def reopen(
    session: AsyncSession, actor: User, preparation_id: uuid.UUID, version: int
) -> Preparation:
    p = await _for_write(session, preparation_id)
    if p.status != "finished":
        raise _invalid_status(p)
    await _check_version(session, p, version)
    await _reverse(session, actor, p, "reopen")
    p.status = "draft"
    p.prepared_date = None
    p.finished_by = None
    p.finished_at = None
    _touch(p, actor)
    _audit(session, "preparation.reopen", actor, p)
    await session.commit()
    return await get_preparation(session, p.id)


async def cancel(
    session: AsyncSession, actor: User, preparation_id: uuid.UUID, version: int, reason: str
) -> Preparation:
    p = await _for_write(session, preparation_id)
    await _check_version(session, p, version)
    was = p.status
    if was == "finished":
        await _reverse(session, actor, p, "cancel")
    now = utcnow()
    p.status = "cancelled"
    p.prepared_date = None
    p.cancel_reason = reason
    p.cancelled_by = actor.id
    p.cancelled_at = now
    _touch(p, actor)
    _audit(session, "preparation.cancel", actor, p, reason=reason, was=was)
    await session.commit()
    return await get_preparation(session, p.id)


# --- Reading -------------------------------------------------------------------------------------


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


async def list_preparations(
    session: AsyncSession,
    *,
    type_: PreparationType | None,
    status: PreparationListStatus,
    include_cancelled: bool,
    date_from: date | None,
    date_to: date | None,
    q: str | None,
    page: int,
    page_size: int,
) -> tuple[list[Preparation], int]:
    P = Preparation
    conditions: list[Any] = []
    if type_:
        conditions.append(P.type == type_)
    if status == "cancelled":
        conditions.append(P.status == "cancelled")
    else:
        shown = ["draft", "finished"] if status == "all" else [status]
        if include_cancelled:
            shown.append("cancelled")
        conditions.append(P.status.in_(shown))
    day = func.coalesce(P.prepared_date, _creation_day())
    if date_from:
        conditions.append(day >= date_from)
    if date_to:
        conditions.append(day <= date_to)
    if q and q.strip():
        pattern = f"%{_escape_like(q.strip())}%"
        name_matches = or_(
            InventoryMaterial.name_en.ilike(pattern, escape="\\"),
            InventoryMaterial.name_km.ilike(pattern, escape="\\"),
        )
        line_material = (
            select(PreparationLine.id)
            .join(InventoryMaterial, InventoryMaterial.id == PreparationLine.material_id)
            .where(PreparationLine.preparation_id == P.id, name_matches)
            .exists()
        )
        satay_material = (
            select(InventoryMaterial.id)
            .where(InventoryMaterial.prep_role.in_(SATAY_ROLES), name_matches)
            .exists()
        )
        conditions.append(
            or_(
                P.code.ilike(pattern, escape="\\"),
                line_material,
                and_(P.type == SATAY, satay_material),
            )
        )
    total = await session.scalar(select(func.count(P.id)).where(*conditions)) or 0
    rows = await session.scalars(
        select(P)
        .where(*conditions)
        .order_by(day.desc(), P.code.desc(), P.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return list(rows), total


async def stats(session: AsyncSession) -> PreparationStats:
    P, L = Preparation, PreparationLine
    month_start = business_today().replace(day=1)
    next_month = (month_start + timedelta(days=32)).replace(day=1)
    in_month = [
        P.status == "finished",
        P.prepared_date >= month_start,
        P.prepared_date < next_month,
    ]
    drafts = await session.scalar(select(func.count(P.id)).where(P.status == "draft"))
    finished = await session.scalar(select(func.count(P.id)).where(*in_month))
    sachets = dict(
        (
            await session.execute(
                select(L.pack_size, func.coalesce(func.sum(L.sachets), 0))
                .join(P, P.id == L.preparation_id)
                .where(*in_month, L.pack_size.is_not(None))
                .group_by(L.pack_size)
            )
        ).all()
    )
    return PreparationStats(
        drafts=drafts or 0,
        finished_this_month=finished or 0,
        sachets_2_this_month=int(sachets.get(2, 0)),
        sachets_4_this_month=int(sachets.get(4, 0)),
    )


def _fmt(unit: str, value: Decimal | int | None) -> str:
    return str(units.quantize(unit, Decimal(value or 0)))  # type: ignore[arg-type]


async def _balances(session: AsyncSession, codes: set[str]) -> dict[str, InventoryBalance]:
    if not codes:
        return {}
    return {
        b.item_code: b
        for b in await session.scalars(
            select(InventoryBalance)
            .where(InventoryBalance.item_code.in_(codes))
            .execution_options(populate_existing=True)
        )
    }


def _stock(bal: InventoryBalance | None, unit: str) -> str:
    if bal is None:
        return _fmt(unit, 0)
    return _fmt(unit, {"count": bal.count, "kg": bal.kg, "g": bal.g}[unit])


def _material_out(
    m: InventoryMaterial, balances: dict[str, InventoryBalance]
) -> PreparationMaterialOut:
    twin = prepared_code(m.item_code)
    return PreparationMaterialOut(
        id=m.id,
        item_code=m.item_code,
        name_km=m.name_km,
        name_en=m.name_en,
        unit=m.unit,  # type: ignore[arg-type]
        prep_role=m.prep_role,  # type: ignore[arg-type]
        icon_key=m.icon_key,
        icon_url=inventory_service.material_icon_url(m),
        archived=m.archived_at is not None,
        stock=_stock(balances.get(m.item_code), m.unit),
        prepared_stock=_stock(balances.get(twin), m.unit) if m.prep_role == "packaging" else None,
    )


async def material_options(session: AsyncSession) -> list[PreparationMaterialOut]:
    """Active packaging materials (preparable 1:1) with their stock, by English name."""
    rows = sorted(
        await session.scalars(
            select(InventoryMaterial).where(
                InventoryMaterial.prep_role == "packaging", InventoryMaterial.archived_at.is_(None)
            )
        ),
        key=lambda m: m.name_en.lower(),
    )
    codes = {c for m in rows for c in (m.item_code, prepared_code(m.item_code))}
    balances = await _balances(session, codes)
    return [_material_out(m, balances) for m in rows]


def _positive(value: Decimal | int | None) -> bool:
    return value is not None and value > 0


def _items(
    p: Preparation,
    roles: dict[str, InventoryMaterial],
    materials: dict[uuid.UUID, InventoryMaterial],
) -> tuple[list[PreparationItemOut], list[PreparationItemOut]]:
    """What the lines take and make (lines' entered values > 0 only)."""
    inputs: list[PreparationItemOut] = []
    outputs: list[PreparationItemOut] = []

    def material_item(
        m: InventoryMaterial, code: str, unit: str, qty: Decimal
    ) -> PreparationItemOut:
        return PreparationItemOut(
            item_code=code,
            name_en=m.name_en,
            name_km=m.name_km,
            unit=unit,  # type: ignore[arg-type]
            quantity=_fmt(unit, qty),
            material_id=m.id,
            icon_key=m.icon_key,
        )

    if p.type == SATAY:
        sauce = roles.get(SATAY_SAUCE)
        grams = sum((line.satay_g for line in p.lines if _positive(line.satay_g)), Decimal(0))
        if sauce is not None and grams:
            inputs.append(material_item(sauce, sauce.item_code, "g", grams))
        for line in p.lines:
            zip_bag = roles.get(ZIP_BAG_ROLES[line.pack_size or 2])
            if zip_bag is not None and _positive(line.quantity):
                unit = line.unit or zip_bag.unit
                inputs.append(material_item(zip_bag, zip_bag.item_code, unit, line.quantity))  # type: ignore[arg-type]
            if _positive(line.sachets):
                item = ITEMS_BY_CODE[SATAY_SACHETS[line.pack_size or 2]]
                outputs.append(
                    PreparationItemOut(
                        item_code=item.code,
                        name_en=item.name_en,
                        name_km=item.name_km,
                        unit="count",
                        quantity=str(line.sachets),
                    )
                )
    else:
        for line in p.lines:
            m = materials.get(line.material_id) if line.material_id else None
            if m is None or not _positive(line.quantity):
                continue
            unit = line.unit or m.unit
            assert line.quantity is not None
            inputs.append(material_item(m, m.item_code, unit, line.quantity))
            outputs.append(material_item(m, prepared_code(m.item_code), unit, line.quantity))
    return inputs, outputs


async def _users(session: AsyncSession, ids: set[uuid.UUID | None]) -> dict[uuid.UUID, User]:
    wanted = {i for i in ids if i is not None}
    if not wanted:
        return {}
    return {u.id: u for u in await session.scalars(select(User).where(User.id.in_(wanted)))}


def _ref(users: dict[uuid.UUID, User], user_id: uuid.UUID | None) -> UserRef | None:
    return UserRef.model_validate(users[user_id]) if user_id in users else None


async def preparation_out(session: AsyncSession, p: Preparation) -> PreparationOut:
    roles = await _role_materials(session) if p.type == SATAY else {}
    materials = await _materials(
        session, {line.material_id for line in p.lines if line.material_id}
    )
    every = [*roles.values(), *materials.values()]
    codes = {c for m in every for c in (m.item_code, prepared_code(m.item_code))}
    balances = await _balances(session, codes)
    users = await _users(session, {p.created_by, p.updated_by, p.finished_by, p.cancelled_by})
    inputs, outputs = _items(p, roles, materials)
    lines = []
    for line in p.lines:
        m = materials.get(line.material_id) if line.material_id else None
        satay = line.pack_size is not None
        lines.append(
            PreparationLineOut(
                id=line.id,
                pack_size=line.pack_size,  # type: ignore[arg-type]
                satay_g=_fmt("g", line.satay_g) if line.satay_g is not None else None,
                zip_bag_qty=_fmt(line.unit or "kg", line.quantity)
                if satay and line.quantity is not None
                else None,
                sachets=line.sachets,
                material=_material_out(m, balances) if m is not None else None,
                quantity=_fmt(line.unit or "kg", line.quantity)
                if not satay and line.quantity is not None
                else None,
                unit=line.unit,  # type: ignore[arg-type]
            )
        )

    def role(name: str) -> PreparationMaterialOut | None:
        m = roles.get(name)
        return _material_out(m, balances) if m is not None else None

    return PreparationOut(
        id=p.id,
        code=p.code,
        type=p.type,  # type: ignore[arg-type]
        status=p.status,  # type: ignore[arg-type]
        prepared_date=p.prepared_date,
        note=p.note,
        cancel_reason=p.cancel_reason,
        version=p.version,
        lines=lines,
        satay_materials=SatayMaterialsOut(
            satay_sauce=role(SATAY_SAUCE),
            zip_bag_2=role(ZIP_BAG_ROLES[2]),
            zip_bag_4=role(ZIP_BAG_ROLES[4]),
        )
        if p.type == SATAY
        else None,
        inputs=inputs,
        outputs=outputs,
        created_by=_ref(users, p.created_by),
        created_at=p.created_at,
        updated_by=_ref(users, p.updated_by),
        updated_at=p.updated_at,
        finished_by=_ref(users, p.finished_by),
        finished_at=p.finished_at,
        cancelled_by=_ref(users, p.cancelled_by),
        cancelled_at=p.cancelled_at,
    )


async def list_items(session: AsyncSession, rows: list[Preparation]) -> list[PreparationListItem]:
    roles = await _role_materials(session) if any(p.type == SATAY for p in rows) else {}
    materials = await _materials(
        session, {line.material_id for p in rows for line in p.lines if line.material_id}
    )
    users = await _users(session, {p.created_by for p in rows})
    items = []
    for p in rows:
        _, outputs = _items(p, roles, materials)
        items.append(
            PreparationListItem(
                id=p.id,
                code=p.code,
                type=p.type,  # type: ignore[arg-type]
                status=p.status,  # type: ignore[arg-type]
                prepared_date=p.prepared_date,
                created_at=p.created_at,
                outputs=outputs,
                created_by=_ref(users, p.created_by),
            )
        )
    return items
