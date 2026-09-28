from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import get_settings

_settings = get_settings()

_engine_kwargs: dict[str, Any] = {"pool_pre_ping": True}
if _settings.db_null_pool:
    _engine_kwargs = {"poolclass": NullPool}

engine = create_async_engine(_settings.database_url, **_engine_kwargs)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session
