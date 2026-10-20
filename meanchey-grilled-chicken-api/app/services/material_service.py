"""Inventory materials: items that don't come from production (string, skewers, sauces, bags...).

- **Stock** (`inventory.materials_stock`): `add_stock` (quantity > 0) and `remove_stock`
  (quantity > 0 and a reason), through `inventory_service.apply_movements`, so balances never go
  below zero (INVENTORY_INSUFFICIENT). Quantities follow the material's unit
  (app/inventory/units.py: count whole, kg 3 decimals, g 1 decimal, m2 2 decimals).
- **Managing** (`inventory.materials_manage`): create, edit (names, unit), archive, restore.
  - Names are unique among active materials, per language, case-insensitive
    (DUPLICATE_MATERIAL_NAME; partial unique indexes are the safety net).
  - Unit kg <-> g: always; the balance is converted (rounded to the new unit's precision) and one
    `material_unit_change` movement records the old unit out and the new unit in. To / from
    count or m2 (square metres, which convert to nothing): only before the first movement
    (MATERIAL_UNIT_LOCKED).
  - Archived materials keep their balance and history but leave the Raw list and the pickers;
    their stock can't change (MATERIAL_ARCHIVED). Restore checks the names again.
  - System materials (`system_code`, e.g. Marinade sauce): renamable, kg <-> g allowed; never
    archived or switched to count or m2 (MATERIAL_SYSTEM_LOCKED).
- Every write locks the material row (`FOR UPDATE`), so a unit change, an archive and a stock
  change on the same material take turns; step 2 reads the marinade row with a share lock.
- **Defaults** are seeded once (`ensure_defaults`, at startup, flag in `app_settings`); Marinade
  sauce is re-created on every start if it's missing, because step 2 needs it.
- **Icons:** `icon_key` names a picture bundled with the UI (the defaults have one); an uploaded
  icon (`set_icon`: PNG / JPEG / WebP, at most 1 MB, decoded to check it, center-cropped and
  resized to a 256 px square PNG) is shown before it. `delete_icon` removes the upload.
- **Preparation role** (`prep_role`, services/preparation_service.py): `packaging` (the default
  for new materials) gives the material a **prepared twin** (`<item_code>_prepared`, Prepared
  section), whose balance row is created with the material; `satay_sauce` / `zip_bag_2` /
  `zip_bag_4` are the satay sachet inputs; `none` (Marinade sauce) isn't preparable. Not editable
  in the UI yet. A kg <-> g switch converts the twin's balance too (its own
  `material_unit_change` movement); switching to / from count needs no movements on either.
- Audit: `material.create`, `material.update` (changes), `material.archive`, `material.restore`,
  `material.stock_add`, `material.stock_remove` (`reason`); `entity_type = material`. An icon
  change is a `material.update` with `changes.icon = "changed" / "removed"` (never the bytes).
"""

import io
import uuid
from decimal import Decimal
from typing import Any

from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy import exists, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import undefer

from app.core.errors import AppError, ErrorCode
from app.inventory import units
from app.inventory.catalog import MARINADE, MATERIAL_PREFIX, prepared_code
from app.models import AppSetting, InventoryBalance, InventoryMaterial, InventoryMovement, User
from app.models.base import utcnow
from app.schemas.common import UserRef
from app.schemas.material import (
    MaterialCreate,
    MaterialOut,
    MaterialUpdate,
    StockAddIn,
    StockRemoveIn,
)
from app.services import inventory_service
from app.services.audit_service import record

ENTITY = "material"
SEEDED_KEY = "inventory_materials_seeded"
# (system_code, name_km, name_en, unit, icon_key, prep_role). All start at 0. The icon keys are
# pictures bundled with the UI (src/assets/inventory/materials/); migration 0015 backfilled them,
# migration 0017 the preparation roles; migration 0023 renamed the kg stickers, added the m2 ones.
DEFAULTS: tuple[tuple[str | None, str, str, units.Unit, str, str], ...] = (
    (None, "ខ្សែ", "String", "kg", "string", "packaging"),
    (None, "ចង្កាក់", "Skewer", "kg", "skewer", "packaging"),
    (
        None,
        "ស្ទីកគ័រ (កញ្ចប់ ២ ដុំ) · គ.ក",
        "Sticker (2-piece packs) · kg",
        "kg",
        "sticker_2",
        "packaging",
    ),
    (
        None,
        "ស្ទីកគ័រ (កញ្ចប់ ៤ ដុំ) · គ.ក",
        "Sticker (4-piece packs) · kg",
        "kg",
        "sticker_4",
        "packaging",
    ),
    (
        None,
        "ស្ទីកគ័រ (កញ្ចប់ ២ ដុំ) · ម៉ែត្រការ៉េ",
        "Sticker (2-piece packs) · m²",
        "m2",
        "sticker_2_m2",
        "packaging",
    ),
    (
        None,
        "ស្ទីកគ័រ (កញ្ចប់ ៤ ដុំ) · ម៉ែត្រការ៉េ",
        "Sticker (4-piece packs) · m²",
        "m2",
        "sticker_4_m2",
        "packaging",
    ),
    (MARINADE, "ទឹកប្រឡាក់", "Marinade sauce", "g", "marinade", "none"),
    (None, "សាតេ", "Satay sauce", "g", "satay", "satay_sauce"),
    (None, "ថង់ Zip 7 (កញ្ចប់ ២ ដុំ)", "Zip bag 7 (2-piece packs)", "kg", "zip_bag_2", "zip_bag_2"),
    (None, "ថង់ Zip 7 (កញ្ចប់ ៤ ដុំ)", "Zip bag 7 (4-piece packs)", "kg", "zip_bag_4", "zip_bag_4"),
    (None, "ថង់បឺតខ្យល់", "Vacuum bag", "kg", "vacuum_bag", "packaging"),
)
# One material each (partial unique index uq_inventory_materials_prep_role).
SINGLE_PREP_ROLES = ("satay_sauce", "zip_bag_2", "zip_bag_4")
ICON_MAX_BYTES = 1024 * 1024
ICON_SIZE = 256
# A small file can still decode to a huge bitmap; refuse it before decoding.
ICON_MAX_PIXELS = 25_000_000
ICON_FORMATS = {"PNG", "JPEG", "WEBP"}
_MARINADE_DEFAULT = next(d for d in DEFAULTS if d[0] == MARINADE)


# --- Seeding -------------------------------------------------------------------------------------


async def _new_code(session: AsyncSession) -> str:
    while True:
        code = f"{MATERIAL_PREFIX}{uuid.uuid4().hex[:8]}"
        taken = await session.scalar(select(exists().where(InventoryMaterial.item_code == code)))
        if not taken:
            return code


async def _name_taken(
    session: AsyncSession, column: Any, name: str, exclude: uuid.UUID | None = None
) -> bool:
    stmt = select(InventoryMaterial.id).where(
        func.lower(column) == name.lower(), InventoryMaterial.archived_at.is_(None)
    )
    if exclude is not None:
        stmt = stmt.where(InventoryMaterial.id != exclude)
    return (await session.scalar(stmt.limit(1))) is not None


async def _add(
    session: AsyncSession,
    name_km: str,
    name_en: str,
    unit: units.Unit,
    *,
    system_code: str | None = None,
    icon_key: str | None = None,
    prep_role: str = "packaging",
    actor: User | None = None,
) -> InventoryMaterial:
    material = InventoryMaterial(
        item_code=await _new_code(session),
        name_km=name_km,
        name_en=name_en,
        unit=unit,
        system_code=system_code,
        icon_key=icon_key,
        prep_role=prep_role,
        created_by=actor.id if actor else None,
        updated_by=actor.id if actor else None,
    )
    session.add(material)
    await session.flush()
    codes = [material.item_code]
    if prep_role == "packaging":
        codes.append(prepared_code(material.item_code))
    await inventory_service.ensure_balances(session, codes)
    return material


async def ensure_defaults(session: AsyncSession) -> None:
    """Seed the default materials once; make sure Marinade sauce exists. Idempotent; the caller
    commits (bootstrap)."""
    seeded = await session.get(AppSetting, SEEDED_KEY)
    if seeded is None:
        for system_code, name_km, name_en, unit, icon_key, prep_role in DEFAULTS:
            if system_code and await inventory_service.marinade_material(session):
                continue
            # Someone may already have a material of that name: don't duplicate it.
            if await _name_taken(session, InventoryMaterial.name_en, name_en) or await _name_taken(
                session, InventoryMaterial.name_km, name_km
            ):
                continue
            if prep_role in SINGLE_PREP_ROLES and await session.scalar(
                select(exists().where(InventoryMaterial.prep_role == prep_role))
            ):
                prep_role = "packaging"
            await _add(
                session,
                name_km,
                name_en,
                unit,
                system_code=system_code,
                icon_key=icon_key,
                prep_role=prep_role,
            )
        session.add(AppSetting(key=SEEDED_KEY, value="1"))
        await session.flush()
    if await inventory_service.marinade_material(session) is None:
        _, name_km, name_en, unit, icon_key, _role = _MARINADE_DEFAULT
        # An active material with that name becomes the system one; otherwise create it.
        existing = await session.scalar(
            select(InventoryMaterial).where(
                func.lower(InventoryMaterial.name_en) == name_en.lower(),
                InventoryMaterial.archived_at.is_(None),
            )
        )
        if existing is not None and existing.unit != "count":
            existing.system_code = MARINADE
            existing.icon_key = existing.icon_key or icon_key
            if existing.prep_role == "packaging":
                existing.prep_role = "none"
            await session.flush()
        else:
            await _add(
                session,
                name_km,
                name_en,
                unit,
                system_code=MARINADE,
                icon_key=icon_key,
                prep_role="none",
            )


# --- Reading -------------------------------------------------------------------------------------


async def get_material(
    session: AsyncSession,
    material_id: uuid.UUID,
    *,
    lock: bool = False,
    with_icon: bool = False,
) -> InventoryMaterial:
    stmt = select(InventoryMaterial).where(InventoryMaterial.id == material_id)
    if with_icon:
        stmt = stmt.options(undefer(InventoryMaterial.icon))
    if lock:
        stmt = stmt.with_for_update()
    material = await session.scalar(stmt.execution_options(populate_existing=True))
    if material is None:
        raise AppError(404, ErrorCode.MATERIAL_NOT_FOUND, "Material not found")
    return material


async def _has_movements(session: AsyncSession, code: str) -> bool:
    return bool(await session.scalar(select(exists().where(InventoryMovement.item_code == code))))


async def materials_out(
    session: AsyncSession, materials: list[InventoryMaterial]
) -> list[MaterialOut]:
    codes = [m.item_code for m in materials]
    balances = {
        b.item_code: b
        for b in await session.scalars(
            select(InventoryBalance)
            .where(InventoryBalance.item_code.in_(codes))
            .execution_options(populate_existing=True)
        )
    }
    moved = set(
        await session.scalars(
            select(InventoryMovement.item_code)
            .where(InventoryMovement.item_code.in_(codes))
            .distinct()
        )
    )
    user_ids = {
        u for m in materials for u in (m.archived_by, m.created_by, m.updated_by) if u is not None
    }
    users = (
        {u.id: u for u in await session.scalars(select(User).where(User.id.in_(user_ids)))}
        if user_ids
        else {}
    )

    def ref(user_id: uuid.UUID | None) -> UserRef | None:
        return UserRef.model_validate(users[user_id]) if user_id in users else None

    out = []
    for m in materials:
        bal = balances.get(m.item_code)
        out.append(
            MaterialOut(
                id=m.id,
                item_code=m.item_code,
                name_km=m.name_km,
                name_en=m.name_en,
                unit=m.unit,  # type: ignore[arg-type]
                system_code=m.system_code,
                icon_key=m.icon_key,
                icon_url=inventory_service.material_icon_url(m),
                prep_role=m.prep_role,  # type: ignore[arg-type]
                count=(bal.count if bal and bal.count is not None else 0)
                if m.unit == "count"
                else None,
                kg=(bal.kg if bal and bal.kg is not None else Decimal(0))
                if m.unit == "kg"
                else None,
                g=(bal.g if bal and bal.g is not None else Decimal(0)) if m.unit == "g" else None,
                m2=(bal.m2 if bal and bal.m2 is not None else Decimal(0))
                if m.unit == "m2"
                else None,
                has_movements=m.item_code in moved,
                archived_at=m.archived_at,
                archived_by=ref(m.archived_by),
                created_by=ref(m.created_by),
                created_at=m.created_at,
                updated_by=ref(m.updated_by),
                updated_at=m.updated_at,
            )
        )
    return out


async def material_out(session: AsyncSession, material: InventoryMaterial) -> MaterialOut:
    return (await materials_out(session, [material]))[0]


async def list_materials(session: AsyncSession, *, include_archived: bool) -> list[MaterialOut]:
    """Active materials by English name; archived ones after them when asked."""
    stmt = select(InventoryMaterial)
    if not include_archived:
        stmt = stmt.where(InventoryMaterial.archived_at.is_(None))
    rows = list(await session.scalars(stmt))
    rows.sort(key=lambda m: (m.archived_at is not None, m.name_en.lower()))
    return await materials_out(session, rows)


# --- Managing ------------------------------------------------------------------------------------


def _duplicate(fields: list[str]) -> AppError:
    return AppError(
        409,
        ErrorCode.DUPLICATE_MATERIAL_NAME,
        "Another active material already has this name",
        {"fields": fields},
    )


async def _check_names(
    session: AsyncSession, name_km: str, name_en: str, exclude: uuid.UUID | None = None
) -> None:
    taken = [
        field
        for field, column, name in (
            ("name_km", InventoryMaterial.name_km, name_km),
            ("name_en", InventoryMaterial.name_en, name_en),
        )
        if await _name_taken(session, column, name, exclude)
    ]
    if taken:
        raise _duplicate(taken)


async def _flush_names(session: AsyncSession) -> None:
    """A concurrent create / rename may still collide: the unique indexes decide."""
    try:
        await session.flush()
    except IntegrityError as e:
        await session.rollback()
        raise _duplicate([]) from e


def _audit(
    session: AsyncSession, action: str, actor: User, m: InventoryMaterial, **details: Any
) -> None:
    record(
        session,
        action,
        actor_id=actor.id,
        entity_type=ENTITY,
        entity_id=m.id,
        details={"item_code": m.item_code, "name_en": m.name_en, "name_km": m.name_km, **details},
    )


def _system_locked(message: str) -> AppError:
    return AppError(409, ErrorCode.MATERIAL_SYSTEM_LOCKED, message)


def _touch(m: InventoryMaterial, actor: User) -> None:
    m.updated_by = actor.id
    m.updated_at = utcnow()


async def create_material(
    session: AsyncSession, actor: User, data: MaterialCreate
) -> InventoryMaterial:
    await _check_names(session, data.name_km, data.name_en)
    material = await _add(session, data.name_km, data.name_en, data.unit, actor=actor)
    await _flush_names(session)
    _audit(session, "material.create", actor, material, unit=material.unit)
    await session.commit()
    return material


def _amount(bal: InventoryBalance, unit: units.Unit) -> Decimal:
    value = {"count": bal.count, "kg": bal.kg, "g": bal.g, "m2": bal.m2}[unit]
    return Decimal(value or 0)


def _set_amount(bal: InventoryBalance, unit: units.Unit, value: Decimal) -> None:
    """Keep exactly the column of `unit` (the others null)."""
    bal.count = int(value) if unit == "count" else None
    bal.kg = value if unit == "kg" else None
    bal.g = value if unit == "g" else None
    bal.m2 = value if unit == "m2" else None


async def _change_unit(
    session: AsyncSession, actor: User, m: InventoryMaterial, new: units.Unit
) -> dict[str, str]:
    """Switch the unit; returns the balance before / after for the audit entry."""
    old: units.Unit = m.unit  # type: ignore[assignment]
    if m.system_code and new in ("count", "m2"):
        raise _system_locked("A material the app relies on can't be counted in pieces or in m²")
    twin = prepared_code(m.item_code)
    # The prepared twin (when it has a balance row) has the material's unit: it switches too.
    has_twin = await session.get(InventoryBalance, twin) is not None
    codes = [m.item_code, twin] if has_twin else [m.item_code]
    balances = await inventory_service.lock_balances(session, codes)
    before = _amount(balances[m.item_code], old)
    after = Decimal(0)
    if units.same_measure(old, new):
        now = utcnow()
        for code in codes:
            row = balances[code]
            amount_before = _amount(row, old)
            amount_after = units.convert(amount_before, old, new)
            if code == m.item_code:
                after = amount_after
            _set_amount(row, new, amount_after)
            row.updated_at = now
            if code == twin and not amount_before:
                # An empty twin just switches unit: no history row.
                continue
            deltas: dict[str, Decimal | None] = {"count": None, "kg": None, "g": None, "m2": None}
            deltas[old] = -amount_before
            deltas[new] = amount_after
            session.add(
                InventoryMovement(
                    item_code=code,
                    count_delta=None,
                    kg_delta=deltas["kg"],
                    g_delta=deltas["g"],
                    m2_delta=deltas["m2"],
                    source="material_unit_change",
                    reason=f"{old} -> {new}",
                    balance_kg_after=row.kg,
                    balance_g_after=row.g,
                    balance_m2_after=row.m2,
                    created_by=actor.id,
                    created_at=now,
                )
            )
    else:
        if await _has_movements(session, m.item_code) or await _has_movements(session, twin):
            raise AppError(
                409,
                ErrorCode.MATERIAL_UNIT_LOCKED,
                "Switching to or from count or m² is only possible before the first stock entry",
                {"unit": old},
            )
        for code in codes:
            _set_amount(balances[code], new, Decimal(0))
    m.unit = new
    return {
        "from": f"{units.quantize(old, before)} {old}",
        "to": f"{units.quantize(new, after)} {new}",
    }


async def update_material(
    session: AsyncSession, actor: User, material_id: uuid.UUID, data: MaterialUpdate
) -> InventoryMaterial:
    m = await get_material(session, material_id, lock=True)
    fields = data.model_fields_set
    name_km = data.name_km if "name_km" in fields and data.name_km is not None else m.name_km
    name_en = data.name_en if "name_en" in fields and data.name_en is not None else m.name_en
    if m.archived_at is None and (name_km != m.name_km or name_en != m.name_en):
        await _check_names(session, name_km, name_en, exclude=m.id)
    changes: dict[str, Any] = {}
    if name_km != m.name_km:
        changes["name_km"] = [m.name_km, name_km]
        m.name_km = name_km
    if name_en != m.name_en:
        changes["name_en"] = [m.name_en, name_en]
        m.name_en = name_en
    if "unit" in fields and data.unit is not None and data.unit != m.unit:
        old = m.unit
        balance = await _change_unit(session, actor, m, data.unit)
        changes["unit"] = [old, data.unit]
        changes["balance"] = [balance["from"], balance["to"]]
    if changes:
        _touch(m, actor)
        await _flush_names(session)
        _audit(session, "material.update", actor, m, changes=changes)
        await session.commit()
    return m


async def archive_material(
    session: AsyncSession, actor: User, material_id: uuid.UUID
) -> InventoryMaterial:
    m = await get_material(session, material_id, lock=True)
    if m.system_code:
        raise _system_locked("A material the app relies on can't be archived")
    if m.archived_at is None:
        m.archived_at = utcnow()
        m.archived_by = actor.id
        _touch(m, actor)
        bal = await session.get(InventoryBalance, m.item_code)
        amount = _amount(bal, m.unit) if bal else Decimal(0)  # type: ignore[arg-type]
        _audit(
            session,
            "material.archive",
            actor,
            m,
            balance=f"{units.quantize(m.unit, amount)} {m.unit}",  # type: ignore[arg-type]
        )
        await session.commit()
    return m


async def restore_material(
    session: AsyncSession, actor: User, material_id: uuid.UUID
) -> InventoryMaterial:
    m = await get_material(session, material_id, lock=True)
    if m.archived_at is not None:
        await _check_names(session, m.name_km, m.name_en, exclude=m.id)
        m.archived_at = None
        m.archived_by = None
        _touch(m, actor)
        await _flush_names(session)
        _audit(session, "material.restore", actor, m)
        await session.commit()
    return m


# --- Icon --------------------------------------------------------------------------------------


def _invalid_icon(message: str) -> AppError:
    return AppError(
        422,
        ErrorCode.VALIDATION_ERROR,
        message,
        {"fields": [{"loc": ["body", "file"], "type": "value_error", "msg": message}]},
    )


def prepare_icon(data: bytes) -> bytes:
    """Validate an uploaded icon (decoded, not trusted by name or declared type) and turn it into
    an ICON_SIZE square PNG: center-cropped, transparency kept."""
    if not data:
        raise _invalid_icon("The file is empty")
    if len(data) > ICON_MAX_BYTES:
        raise _invalid_icon(f"The icon must be at most {ICON_MAX_BYTES // (1024 * 1024)} MB")
    invalid = "The icon must be a PNG, JPEG or WebP image"
    try:
        image = Image.open(io.BytesIO(data))
        if image.width * image.height > ICON_MAX_PIXELS:
            raise _invalid_icon("The icon image is too large")
        if image.format not in ICON_FORMATS:
            raise _invalid_icon(invalid)
        image.load()
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as e:
        raise _invalid_icon(invalid) from e
    # Phone photos carry their rotation in EXIF.
    image = ImageOps.exif_transpose(image).convert("RGBA")
    square = ImageOps.fit(image, (ICON_SIZE, ICON_SIZE), Image.Resampling.LANCZOS)
    out = io.BytesIO()
    square.save(out, format="PNG", optimize=True)
    return out.getvalue()


async def set_icon(
    session: AsyncSession, actor: User, material_id: uuid.UUID, data: bytes
) -> InventoryMaterial:
    icon = prepare_icon(data)
    m = await get_material(session, material_id, lock=True, with_icon=True)
    m.icon, m.icon_mime = icon, "image/png"
    _touch(m, actor)
    _audit(session, "material.update", actor, m, changes={"icon": "changed"})
    await session.commit()
    return m


async def delete_icon(
    session: AsyncSession, actor: User, material_id: uuid.UUID
) -> InventoryMaterial:
    m = await get_material(session, material_id, lock=True, with_icon=True)
    if m.icon_mime is not None:
        m.icon, m.icon_mime = None, None
        _touch(m, actor)
        _audit(session, "material.update", actor, m, changes={"icon": "removed"})
        await session.commit()
    return m


async def get_icon(session: AsyncSession, material_id: uuid.UUID) -> tuple[bytes, str]:
    m = await get_material(session, material_id, with_icon=True)
    if m.icon is None or m.icon_mime is None:
        raise AppError(404, ErrorCode.NOT_FOUND, "No icon")
    return m.icon, m.icon_mime


# --- Stock ---------------------------------------------------------------------------------------


def _check_quantity(unit: units.Unit, quantity: Decimal) -> Decimal:
    if quantity <= 0:
        msg = "The quantity must be more than 0"
    elif not units.has_precision(unit, quantity):
        msg = {
            "count": "Whole numbers only",
            "kg": "At most 3 decimals",
            "g": "At most 1 decimal",
            "m2": "At most 2 decimals",
        }[unit]
    elif quantity > units.MAX_QUANTITY[unit]:
        msg = "The quantity is too large"
    else:
        return units.quantize(unit, quantity)
    raise AppError(
        422,
        ErrorCode.VALIDATION_ERROR,
        "Invalid quantity",
        {
            "fields": [{"loc": ["body", "quantity"], "type": "value_error", "msg": msg}],
            "unit": unit,
        },
    )


def _delta(m: InventoryMaterial, signed: Decimal, reason: str | None = None):
    unit = m.unit
    return inventory_service.Delta(
        m.item_code,
        count=int(signed) if unit == "count" else None,
        kg=signed if unit == "kg" else None,
        g=signed if unit == "g" else None,
        m2=signed if unit == "m2" else None,
        reason=reason,
    )


async def _stock_change(
    session: AsyncSession,
    actor: User,
    material_id: uuid.UUID,
    quantity: Decimal,
    *,
    remove: bool,
    reason: str | None = None,
) -> InventoryMaterial:
    m = await get_material(session, material_id, lock=True)
    if m.archived_at is not None:
        raise AppError(
            409, ErrorCode.MATERIAL_ARCHIVED, "This material is archived; restore it first"
        )
    unit: units.Unit = m.unit  # type: ignore[assignment]
    qty = _check_quantity(unit, quantity)
    await inventory_service.apply_movements(
        session,
        actor,
        [_delta(m, -qty if remove else qty, reason)],
        source="material_remove" if remove else "material_add",
    )
    bal = await session.get(InventoryBalance, m.item_code)
    assert bal is not None
    details: dict[str, Any] = {
        "quantity": str(qty),
        "unit": unit,
        "balance_after": str(units.quantize(unit, _amount(bal, unit))),
    }
    if reason is not None:
        details["reason"] = reason
    _audit(
        session, "material.stock_remove" if remove else "material.stock_add", actor, m, **details
    )
    await session.commit()
    return m


async def add_stock(
    session: AsyncSession, actor: User, material_id: uuid.UUID, data: StockAddIn
) -> InventoryMaterial:
    return await _stock_change(session, actor, material_id, data.quantity, remove=False)


async def remove_stock(
    session: AsyncSession, actor: User, material_id: uuid.UUID, data: StockRemoveIn
) -> InventoryMaterial:
    return await _stock_change(
        session, actor, material_id, data.quantity, remove=True, reason=data.reason
    )
