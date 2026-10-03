"""Business info: the single `business_settings` row printed on delivery notes.

- The row is seeded by migration 0013 with the business name; `get_row` recreates it with the
  defaults if it's ever missing (e.g. a truncated test database).
- Text fields are replaced together (`BusinessIn`); the phone is normalized (core/phones.py).
- The logo is a PNG or JPEG upload of at most 500 kB, checked by decoding it (not by its name or
  declared type) and stored resized to at most 400 px wide in the same format.
- Every change writes `settings.business_update` with the changed fields (`[old, new]`); the logo
  shows as `"changed"` / `"removed"`, never its bytes.
"""

import io
from typing import Any

from PIL import Image, UnidentifiedImageError
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import undefer

from app.core.errors import AppError, ErrorCode
from app.core.phones import format_phone, normalize_phone
from app.models import BusinessSettings, User, utcnow
from app.schemas.business import BusinessIn, BusinessOut
from app.schemas.common import UserRef
from app.services.audit_service import record

DEFAULT_NAME_KM = "មាន់អាំងមានជ័យ"
DEFAULT_NAME_EN = "Mean Chey Grilled Chicken"
LOGO_MAX_BYTES = 500 * 1024
LOGO_MAX_WIDTH = 400
# A small file can still decode to a huge bitmap; refuse it before decoding.
LOGO_MAX_PIXELS = 25_000_000
# Pillow format name -> stored MIME type.
_LOGO_FORMATS = {"PNG": "image/png", "JPEG": "image/jpeg"}
TEXT_FIELDS = (
    "name_km",
    "name_en",
    "address_km",
    "address_en",
    "phone",
    "footer_note_km",
    "footer_note_en",
)


async def get_row(
    session: AsyncSession, *, lock: bool = False, with_logo: bool = False
) -> BusinessSettings:
    stmt = select(BusinessSettings).where(BusinessSettings.id == 1)
    if with_logo:
        stmt = stmt.options(undefer(BusinessSettings.logo))
    if lock:
        stmt = stmt.with_for_update()
    row = await session.scalar(stmt.execution_options(populate_existing=True))
    if row is None:
        await session.execute(
            pg_insert(BusinessSettings)
            .values(id=1, name_km=DEFAULT_NAME_KM, name_en=DEFAULT_NAME_EN)
            .on_conflict_do_nothing()
        )
        row = await session.scalar(stmt.execution_options(populate_existing=True))
        assert row is not None
    return row


async def business_out(session: AsyncSession, row: BusinessSettings) -> BusinessOut:
    updated_by = await session.get(User, row.updated_by) if row.updated_by else None
    return BusinessOut(
        name_km=row.name_km,
        name_en=row.name_en,
        address_km=row.address_km,
        address_en=row.address_en,
        phone=row.phone,
        phone_display=format_phone(row.phone),
        footer_note_km=row.footer_note_km,
        footer_note_en=row.footer_note_en,
        has_logo=row.logo_mime is not None,
        logo_mime=row.logo_mime,
        updated_by=UserRef.model_validate(updated_by) if updated_by else None,
        updated_at=row.updated_at,
    )


def _audit(session: AsyncSession, actor: User, changes: dict[str, Any]) -> None:
    record(session, "settings.business_update", actor_id=actor.id, details={"changes": changes})


def _touch(row: BusinessSettings, actor: User) -> None:
    row.updated_by = actor.id
    row.updated_at = utcnow()


async def update(session: AsyncSession, actor: User, data: BusinessIn) -> BusinessSettings:
    row = await get_row(session, lock=True)
    values = data.model_dump()
    values["phone"] = normalize_phone(data.phone)
    changes: dict[str, list[Any]] = {}
    for field in TEXT_FIELDS:
        old, new = getattr(row, field), values[field]
        if old != new:
            changes[field] = [old, new]
            setattr(row, field, new)
    if changes:
        _touch(row, actor)
        _audit(session, actor, changes)
        await session.commit()
    return row


def _invalid_logo(message: str) -> AppError:
    return AppError(
        422,
        ErrorCode.VALIDATION_ERROR,
        message,
        {"fields": [{"loc": ["body", "file"], "type": "value_error", "msg": message}]},
    )


def prepare_logo(data: bytes) -> tuple[bytes, str]:
    """Validate an uploaded logo and shrink it to LOGO_MAX_WIDTH. Returns (bytes, MIME type)."""
    if not data:
        raise _invalid_logo("The file is empty")
    if len(data) > LOGO_MAX_BYTES:
        raise _invalid_logo(f"The logo must be at most {LOGO_MAX_BYTES // 1024} kB")
    try:
        image = Image.open(io.BytesIO(data))
        if image.width * image.height > LOGO_MAX_PIXELS:
            raise _invalid_logo("The logo image is too large")
        image.load()
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as e:
        raise _invalid_logo("The logo must be a PNG or JPEG image") from e
    mime = _LOGO_FORMATS.get(image.format or "")
    if mime is None:
        raise _invalid_logo("The logo must be a PNG or JPEG image")
    if image.width <= LOGO_MAX_WIDTH:
        return data, mime
    height = max(1, round(image.height * LOGO_MAX_WIDTH / image.width))
    resized = image.resize((LOGO_MAX_WIDTH, height), Image.Resampling.LANCZOS)
    out = io.BytesIO()
    if mime == "image/png":
        resized.save(out, format="PNG", optimize=True)
    else:
        resized.convert("RGB").save(out, format="JPEG", quality=88, optimize=True)
    return out.getvalue(), mime


async def set_logo(session: AsyncSession, actor: User, data: bytes) -> BusinessSettings:
    logo, mime = prepare_logo(data)
    row = await get_row(session, lock=True, with_logo=True)
    row.logo, row.logo_mime = logo, mime
    _touch(row, actor)
    _audit(session, actor, {"logo": "changed"})
    await session.commit()
    return row


async def delete_logo(session: AsyncSession, actor: User) -> BusinessSettings:
    row = await get_row(session, lock=True)
    if row.logo_mime is not None:
        row.logo, row.logo_mime = None, None
        _touch(row, actor)
        _audit(session, actor, {"logo": "removed"})
        await session.commit()
    return row
