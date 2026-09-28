import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Permission
from app.permissions.registry import PERMISSIONS

log = logging.getLogger(__name__)


async def sync_registry(session: AsyncSession) -> None:
    """Upsert registry entries into `permissions`; deactivate ones no longer in the registry.

    Does not commit; the caller owns the transaction.
    """
    existing = {p.code: p for p in (await session.scalars(select(Permission))).all()}
    registry_codes: set[str] = set()

    for d in PERMISSIONS:
        registry_codes.add(d.code)
        values = {
            "module": d.module,
            "name_en": d.name_en,
            "name_km": d.name_km,
            "description_en": d.description_en,
            "description_km": d.description_km,
            "assignable_to": [r.value for r in d.assignable_to],
            "is_active": True,
        }
        row = existing.get(d.code)
        if row is None:
            session.add(Permission(code=d.code, **values))
            log.info("permission registered: %s", d.code)
        else:
            for key, value in values.items():
                setattr(row, key, value)

    for code, row in existing.items():
        if code not in registry_codes and row.is_active:
            row.is_active = False
            log.warning("permission removed from registry, marked inactive: %s", code)

    await session.flush()
