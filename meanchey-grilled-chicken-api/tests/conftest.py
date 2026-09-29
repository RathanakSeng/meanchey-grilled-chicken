import os
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parent.parent

# Configure the environment BEFORE any app module is imported.
_dotenv = dotenv_values(ROOT / ".env")
TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL") or _dotenv.get(
    "TEST_DATABASE_URL", "postgresql+asyncpg://meanchey:meanchey@localhost:5432/meanchey_test"
)
TEST_BOT_TOKEN = "123456789:TEST-bot-token-for-init-data-validation"
os.environ.update(
    {
        "DATABASE_URL": TEST_DATABASE_URL,
        "DB_NULL_POOL": "true",
        "JWT_SECRET": "test-secret-0123456789-abcdefghijklmnopqrstuvwxyz",
        "TELEGRAM_BOT_TOKEN": TEST_BOT_TOKEN,
        "SUPERADMIN_INITIAL_PASSWORD": "superadmin",
        "LOGIN_MAX_ATTEMPTS": "5",
        "LOGIN_LOCK_MINUTES": "15",
        # No bot by default; webhook tests install their own runtime. Explicit values also
        # keep the developer's real .env (bot URLs, secrets) out of the test run.
        "BOT_MODE": "off",
        "MINI_APP_URL": "",
        "TELEGRAM_WEBHOOK_URL": "",
        "TELEGRAM_WEBHOOK_SECRET": "",
        "TELEGRAM_WEBHOOK_AUTO_SET": "true",
        "TELEGRAM_DROP_PENDING_UPDATES": "false",
    }
)

import asyncio  # noqa: E402
import uuid  # noqa: E402
from collections.abc import AsyncIterator, Awaitable, Callable  # noqa: E402

import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import select, text  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402

from app.bootstrap import bootstrap  # noqa: E402
from app.core.security import create_access_token, hash_password  # noqa: E402
from app.db import SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Role, User, UserPermission  # noqa: E402
from app.permissions.registry import DEFAULT_PERMISSIONS  # noqa: E402

DEFAULT_PASSWORD = "correct-horse-1"


@pytest.fixture(scope="session", autouse=True)
def _migrated_database() -> None:
    """Recreate the test schema from the Alembic migrations (also exercises them)."""

    async def reset_schema() -> None:
        eng = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
        async with eng.begin() as conn:
            await conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
            await conn.execute(text("CREATE SCHEMA public"))
        await eng.dispose()

    asyncio.run(reset_schema())
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.attributes["configure_logger"] = False
    cfg.attributes["database_url"] = TEST_DATABASE_URL
    command.upgrade(cfg, "head")


@pytest.fixture(autouse=True)
async def _clean_database() -> None:
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "TRUNCATE audit_logs, refresh_tokens, user_permissions, permissions, users, "
                "bot_prefs, app_settings, production_batches, production_batch_counters, "
                "suppliers, customers RESTART IDENTITY CASCADE"
            )
        )
    async with SessionLocal() as session:
        await bootstrap(session)


@pytest.fixture
async def session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as s:
        yield s


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test/api/v1") as c:
        yield c


@pytest.fixture
async def superadmin(session: AsyncSession) -> User:
    user = await session.scalar(select(User).where(User.role == Role.SUPERADMIN))
    assert user is not None
    return user


MakeUser = Callable[..., Awaitable[User]]


@pytest.fixture
def make_user(session: AsyncSession) -> MakeUser:
    """Create a user directly in the DB. Permissions default to the role defaults."""

    async def _make(
        role: Role,
        username: str | None = None,
        *,
        position: str | None = None,
        perms: list[str] | None = None,
        password: str = DEFAULT_PASSWORD,
        must_change_password: bool = False,
        is_active: bool = True,
        telegram_user_id: int | None = None,
        created_by: uuid.UUID | None = None,
    ) -> User:
        if role == Role.STAFF and position is None:
            position = "worker"
        user = User(
            role=role,
            position=position,
            full_name=f"Test {role.value}",
            telegram_username=username or f"{role.value[:5]}_{uuid.uuid4().hex[:10]}",
            telegram_user_id=telegram_user_id,
            password_hash=hash_password(password),
            must_change_password=must_change_password,
            is_active=is_active,
            created_by=created_by,
        )
        session.add(user)
        await session.flush()
        codes = perms if perms is not None else sorted(DEFAULT_PERMISSIONS.get(role, ()))
        for code in codes:
            session.add(UserPermission(user_id=user.id, permission_code=code))
        await session.commit()
        return user

    return _make


def auth(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id)}"}


def assert_error(response, status: int, code: str) -> None:
    assert response.status_code == status, response.text
    assert response.json()["error"]["code"] == code, response.text
