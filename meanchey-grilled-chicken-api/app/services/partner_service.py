"""Generic CRUD for partner lists (suppliers, customers).

Each list is described by a `PartnerKind`; the rules are identical. Access is decided by
permissions alone (`<prefix>.view|create|update|delete`): partners are not users, so there is
no role-scope check.
"""

import re
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.errors import AppError, ErrorCode
from app.core.phones import normalize_phone
from app.models import Customer, PartnerMixin, Supplier, User, utcnow
from app.schemas.partner import (
    PartnerCreate,
    PartnerSort,
    PartnerStats,
    PartnerStatus,
    PartnerUpdate,
)
from app.services.audit_service import record


@dataclass(frozen=True)
class PartnerKind:
    model: type[Supplier] | type[Customer]
    # Singular entity name: audit actions (`supplier.create`) and `audit_logs.entity_type`.
    entity: str
    # Permission prefix and URL segment: `suppliers.view`, `/suppliers`.
    prefix: str
    not_found: ErrorCode

    @property
    def phone_index(self) -> str:
        return f"uq_{self.model.__tablename__}_active_phone"


SUPPLIERS = PartnerKind(Supplier, "supplier", "suppliers", ErrorCode.SUPPLIER_NOT_FOUND)
CUSTOMERS = PartnerKind(Customer, "customer", "customers", ErrorCode.CUSTOMER_NOT_FOUND)

_NON_DIGITS = re.compile(r"\D+")


def _duplicate_phone_error() -> AppError:
    return AppError(409, ErrorCode.DUPLICATE_PHONE, "Phone number is already in use")


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


async def _flush_or_conflict(session: AsyncSession, kind: PartnerKind) -> None:
    """Flush, translating the active-phone unique index violation into DUPLICATE_PHONE."""
    try:
        await session.flush()
    except IntegrityError as e:
        await session.rollback()
        if kind.phone_index in str(e.orig):
            raise _duplicate_phone_error() from e
        raise


async def _phone_taken(
    session: AsyncSession, kind: PartnerKind, phone: str, exclude_id: uuid.UUID | None = None
) -> bool:
    m = kind.model
    stmt = select(m.id).where(m.phone == phone, m.is_active)
    if exclude_id is not None:
        stmt = stmt.where(m.id != exclude_id)
    return (await session.scalar(stmt.limit(1))) is not None


async def get_or_404(session: AsyncSession, kind: PartnerKind, partner_id: uuid.UUID):
    row = await session.get(kind.model, partner_id)
    if row is None:
        raise AppError(404, kind.not_found, f"{kind.entity.capitalize()} not found")
    return row


async def list_partners(
    session: AsyncSession,
    kind: PartnerKind,
    *,
    q: str | None,
    status: PartnerStatus,
    sort: PartnerSort,
    page: int,
    page_size: int,
) -> tuple[list[PartnerMixin], int]:
    m = kind.model
    conditions: list[Any] = []
    if status == "active":
        conditions.append(m.is_active)
    elif status == "inactive":
        conditions.append(m.is_active.is_(False))
    if q and q.strip():
        term = q.strip()
        pattern = f"%{_escape_like(term)}%"
        matches = [m.name.ilike(pattern, escape="\\"), m.location.ilike(pattern, escape="\\")]
        # Phones are stored as digits: "012 345" finds 012345678, "+855 12" finds +85512….
        digits = _NON_DIGITS.sub("", term)
        if digits:
            matches.append(m.phone.contains(digits, autoescape=True))
        conditions.append(or_(*matches))

    order = {
        "name": [func.lower(m.name).asc(), m.created_at.desc()],
        "-name": [func.lower(m.name).desc(), m.created_at.desc()],
        "created_at": [m.created_at.asc()],
        "-created_at": [m.created_at.desc()],
    }[sort]

    total = await session.scalar(select(func.count(m.id)).where(*conditions)) or 0
    items = await session.scalars(
        select(m)
        .where(*conditions)
        .order_by(*order, m.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return list(items), total


def month_start_utc(now: datetime | None = None) -> datetime:
    """Start of the current calendar month in BUSINESS_TIMEZONE, as an aware datetime."""
    tz = get_settings().business_tz
    local = (now or utcnow()).astimezone(tz)
    return local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


async def stats(session: AsyncSession, kind: PartnerKind) -> PartnerStats:
    m = kind.model
    since = month_start_utc()
    row = (
        await session.execute(
            select(
                func.count(m.id).filter(m.is_active),
                func.count(m.id).filter(m.created_at >= since),
                func.count(m.id).filter(m.is_active.is_(False)),
            )
        )
    ).one()
    return PartnerStats(total_active=row[0], new_this_month=row[1], inactive=row[2])


async def create_partner(
    session: AsyncSession, kind: PartnerKind, actor: User, data: PartnerCreate
) -> PartnerMixin:
    phone = normalize_phone(data.phone)
    if phone is not None and await _phone_taken(session, kind, phone):
        raise _duplicate_phone_error()
    row = kind.model(
        name=data.name,
        location=data.location,
        phone=phone,
        created_by=actor.id,
        updated_by=actor.id,
    )
    session.add(row)
    await _flush_or_conflict(session, kind)
    record(
        session,
        f"{kind.entity}.create",
        actor_id=actor.id,
        entity_type=kind.entity,
        entity_id=row.id,
        details={"name": row.name, "location": row.location, "phone": row.phone},
    )
    await session.commit()
    return row


async def update_partner(
    session: AsyncSession, kind: PartnerKind, actor: User, row: PartnerMixin, data: PartnerUpdate
) -> PartnerMixin:
    fields = data.model_fields_set
    changes: dict[str, list[Any]] = {}

    def _set(attr: str, value: Any) -> None:
        old = getattr(row, attr)
        if old != value:
            changes[attr] = [old, value]
            setattr(row, attr, value)

    if "name" in fields and data.name is not None:
        _set("name", data.name)
    if "location" in fields:
        _set("location", data.location)
    if "phone" in fields:
        phone = normalize_phone(data.phone)
        if (
            phone is not None
            and phone != row.phone
            and row.is_active
            and await _phone_taken(session, kind, phone, exclude_id=row.id)
        ):
            raise _duplicate_phone_error()
        _set("phone", phone)

    if changes:
        row.updated_by = actor.id
        row.updated_at = utcnow()
        await _flush_or_conflict(session, kind)
        record(
            session,
            f"{kind.entity}.update",
            actor_id=actor.id,
            entity_type=kind.entity,
            entity_id=row.id,
            details={"name": row.name, "changes": changes},
        )
        await session.commit()
    return row


async def deactivate_partner(
    session: AsyncSession, kind: PartnerKind, actor: User, row: PartnerMixin
) -> PartnerMixin:
    if not row.is_active:
        return row
    now = utcnow()
    row.is_active = False
    row.deleted_at = now
    row.updated_by = actor.id
    row.updated_at = now
    record(
        session,
        f"{kind.entity}.deactivate",
        actor_id=actor.id,
        entity_type=kind.entity,
        entity_id=row.id,
        details={"name": row.name},
    )
    await session.commit()
    return row


async def reactivate_partner(
    session: AsyncSession, kind: PartnerKind, actor: User, row: PartnerMixin
) -> PartnerMixin:
    if row.is_active:
        return row
    if row.phone is not None and await _phone_taken(session, kind, row.phone, exclude_id=row.id):
        raise _duplicate_phone_error()
    row.is_active = True
    row.deleted_at = None
    row.updated_by = actor.id
    row.updated_at = utcnow()
    await _flush_or_conflict(session, kind)
    record(
        session,
        f"{kind.entity}.reactivate",
        actor_id=actor.id,
        entity_type=kind.entity,
        entity_id=row.id,
        details={"name": row.name},
    )
    await session.commit()
    return row


async def user_refs(session: AsyncSession, rows: list[PartnerMixin]) -> dict[uuid.UUID, User]:
    """Users referenced by created_by / updated_by, loaded in one query."""
    ids = {uid for r in rows for uid in (r.created_by, r.updated_by) if uid is not None}
    if not ids:
        return {}
    users = await session.scalars(select(User).where(User.id.in_(ids)))
    return {u.id: u for u in users}
