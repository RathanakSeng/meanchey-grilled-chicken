"""Idempotent startup tasks: sync the permission registry (backfilling role defaults for newly
added permissions), seed the superadmin, make sure every role has a limit row (defaults 2 / 3 / 10;
existing rows are never changed) and (in webhook mode) register the Telegram webhook.

Run with `python -m app.bootstrap`; also runs on API startup.
"""

import asyncio
import logging
from typing import TYPE_CHECKING

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.security import hash_password
from app.models import Role, RoleLimit, User
from app.models.role_limit import DEFAULT_ROLE_LIMITS
from app.permissions.registry import validate_features
from app.permissions.sync import backfill_defaults, sync_registry

if TYPE_CHECKING:
    from app.bot.runtime import TelegramRuntime

log = logging.getLogger(__name__)

_BOOTSTRAP_LOCK_KEY = 815_001


async def seed_superadmin(session: AsyncSession) -> None:
    exists = await session.scalar(select(User.id).where(User.role == Role.SUPERADMIN))
    if exists is not None:
        return
    session.add(
        User(
            role=Role.SUPERADMIN,
            full_name="Super Admin",
            password_hash=hash_password(get_settings().superadmin_initial_password),
            # The superadmin is exempt from the forced first-login password change.
            must_change_password=False,
        )
    )
    await session.flush()
    log.info("seeded superadmin account")


async def seed_role_limits(session: AsyncSession) -> None:
    """Insert the default limit for any role without a row (the migration seeds them too)."""
    await session.execute(
        pg_insert(RoleLimit)
        .values([{"role": r.value, "max_active": n} for r, n in DEFAULT_ROLE_LIMITS.items()])
        .on_conflict_do_nothing(index_elements=[RoleLimit.role])
    )


async def register_webhook(session: AsyncSession, telegram: "TelegramRuntime | None") -> None:
    """Webhook mode + auto-set: make sure Telegram points at our webhook. Never raises."""
    from app.bot.registration import ensure_webhook
    from app.bot.setup import create_bot, create_dispatcher

    if telegram is not None:
        await ensure_webhook(telegram.bot, telegram.dp, session)
        return
    # e.g. `python -m app.bootstrap` before uvicorn starts: use a short-lived bot.
    bot = create_bot()
    try:
        await ensure_webhook(bot, create_dispatcher(), session)
    finally:
        await bot.session.close()


async def bootstrap(session: AsyncSession, telegram: "TelegramRuntime | None" = None) -> None:
    settings = get_settings()
    # Serialize concurrent starts (api + multiple workers / replicas).
    await session.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": _BOOTSTRAP_LOCK_KEY})
    validate_features()  # also runs at import; repeated here so startup fails loudly
    new_codes = await sync_registry(session)
    await backfill_defaults(session, new_codes)
    await seed_superadmin(session)
    await seed_role_limits(session)
    if settings.webhook_enabled and settings.telegram_webhook_auto_set:
        await register_webhook(session, telegram)
    await session.commit()


async def _main() -> None:
    from app.db import SessionLocal, engine

    logging.basicConfig(level=logging.INFO)
    async with SessionLocal() as session:
        await bootstrap(session)
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(_main())
