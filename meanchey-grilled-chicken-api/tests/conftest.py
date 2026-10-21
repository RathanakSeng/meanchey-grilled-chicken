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
        # Tests run scheduler ticks directly (app.attendance.scheduler.run_tick).
        "ATTENDANCE_SCHEDULER_ENABLED": "false",
    }
)

import asyncio  # noqa: E402
import uuid  # noqa: E402
from collections.abc import AsyncIterator, Awaitable, Callable  # noqa: E402
from datetime import date  # noqa: E402
from decimal import Decimal  # noqa: E402

import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import select, text, update  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402

from app.bootstrap import bootstrap  # noqa: E402
from app.core.security import create_access_token, hash_password  # noqa: E402
from app.db import SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import (  # noqa: E402
    AttendanceScheduleVersion,
    InventoryBalance,
    Role,
    User,
    UserPermission,
)
from app.permissions.registry import DEFAULT_PERMISSIONS  # noqa: E402

DEFAULT_PASSWORD = "correct-horse-1"
SCHEDULE_SINCE = date(2000, 1, 1)


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
def _known_bot_username(monkeypatch) -> None:
    """The bot's @username without a getMe call (GET /me/telegram-bot, the route sweeps)."""
    from app.bot import notify

    monkeypatch.setattr(notify, "_bot_username", "meanchey_test_bot")


@pytest.fixture(autouse=True)
async def _clean_database() -> None:
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "TRUNCATE audit_logs, refresh_tokens, user_permissions, permissions, users, "
                "bot_prefs, app_settings, production_batches, production_batch_counters, "
                "suppliers, customers, role_limits, inventory_movements, inventory_balances, "
                "orders, order_counters, business_settings, inventory_materials, preparations, "
                "preparation_counters, attendance_records, attendance_reminders, "
                "attendance_workplaces, attendance_schedule_versions, attendance_holidays, "
                "attendance_holiday_workplaces "
                "RESTART IDENTITY CASCADE"
            )
        )
    async with SessionLocal() as session:
        await bootstrap(session)
        # Schedules apply from long ago, so the tests' fixed dates use them.
        await session.execute(
            update(AttendanceScheduleVersion).values(effective_from=SCHEDULE_SINCE)
        )
        await session.commit()
        await set_marinade_stock(session, MARINADE_TEST_STOCK_G)
        await set_sachet_stock(session, SACHET_TEST_STOCK, SACHET_TEST_STOCK)


# Step 2 Finish takes its marinade_g out of the Marinade sauce material: every test starts with
# plenty on hand (set on the balance directly, so no history row appears). Marinade tests set
# their own amounts with set_marinade_stock.
MARINADE_TEST_STOCK_G = Decimal("1000000.0")


async def set_marinade_stock(session: AsyncSession, grams: Decimal) -> None:
    from app.services.inventory_service import ensure_balances, marinade_material

    material = await marinade_material(session)
    assert material is not None
    await ensure_balances(session, [material.item_code])
    await session.execute(
        update(InventoryBalance)
        .where(InventoryBalance.item_code == material.item_code)
        .values(
            g=grams if material.unit == "g" else None,
            kg=None if material.unit == "g" else grams / 1000,
        )
    )
    await session.commit()


# Step 3 Finish takes one satay sachet per pack: every test starts with plenty of both sizes, set
# on the balances directly (no preparation behind them, so the sachets are taken unattributed).
# Sachet tests set their own amounts with set_sachet_stock or make them with preparations.
SACHET_TEST_STOCK = 1_000_000


async def set_sachet_stock(session: AsyncSession, size_4: int, size_2: int) -> None:
    from app.inventory.catalog import SATAY_SACHET_2, SATAY_SACHET_4
    from app.services.inventory_service import ensure_balances

    await ensure_balances(session, [SATAY_SACHET_4, SATAY_SACHET_2])
    for code, count in ((SATAY_SACHET_4, size_4), (SATAY_SACHET_2, size_2)):
        await session.execute(
            update(InventoryBalance).where(InventoryBalance.item_code == code).values(count=count)
        )
    await session.commit()


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
        workplace_id: uuid.UUID | None = None,
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
            workplace_id=workplace_id,
            untracked_periods=[],
        )
        session.add(user)
        await session.flush()
        codes = perms if perms is not None else sorted(DEFAULT_PERMISSIONS.get(role, ()))
        for code in codes:
            session.add(UserPermission(user_id=user.id, permission_code=code))
        await session.commit()
        return user

    return _make


async def allow_audit(*users: User) -> None:
    """Give general managers the audit log (`audit.view`, off by default; the superadmin's call)."""
    async with SessionLocal() as s:
        for user in users:
            s.add(UserPermission(user_id=user.id, permission_code="audit.view"))
        await s.commit()


def auth(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id)}"}


def assert_error(response, status: int, code: str) -> None:
    assert response.status_code == status, response.text
    assert response.json()["error"]["code"] == code, response.text


@pytest.fixture
def html_documents(monkeypatch) -> None:
    """Delivery notes come back as the template's HTML instead of a PDF: the routes' counting,
    audit and redaction can be checked as text, also where WeasyPrint can't run (Windows)."""
    from app.documents.render import render_html
    from app.services import document_service

    async def fake_render(context: dict) -> bytes:
        return render_html(context).encode()

    monkeypatch.setattr(document_service, "render_pdf", fake_render)


# --- Attendance --------------------------------------------------------------------------------
# A fixed clock (the server's, app.attendance.clock) and a workplace with coordinates.

ATTENDANCE_DAY = "2026-10-13"
WORKPLACE_LAT = 11.562108
WORKPLACE_LNG = 104.888535
METRES_PER_DEGREE_LAT = 111_194.93


def at(hm: str, day: str = ATTENDANCE_DAY):
    """An instant on `day` at local time `hm` ("07:10" or "07:44:59") in BUSINESS_TIMEZONE."""
    from datetime import datetime, time

    from app.config import get_settings

    return datetime.combine(
        datetime.fromisoformat(day).date(), time.fromisoformat(hm), get_settings().business_tz
    )


def position(metres_north: float = 0, accuracy_m: float = 15) -> dict:
    """A check-in body `metres_north` of the workplace."""
    return {
        "latitude": WORKPLACE_LAT + metres_north / METRES_PER_DEGREE_LAT,
        "longitude": WORKPLACE_LNG,
        "accuracy_m": accuracy_m,
    }


@pytest.fixture
def clock(monkeypatch) -> Callable[[str], None]:
    """`clock("07:10")` (or a datetime) sets the server's time for attendance."""
    from datetime import datetime

    from app.attendance import clock as attendance_clock

    state: dict = {"now": at("08:00")}
    monkeypatch.setattr(attendance_clock, "now", lambda: state["now"])

    def _set(value) -> None:
        state["now"] = value if isinstance(value, datetime) else at(value)

    return _set


@pytest.fixture
async def workplace(session: AsyncSession):
    """The default workplace with its position set (radius 100 m)."""
    from app.models import AttendanceWorkplace

    w = await session.scalar(select(AttendanceWorkplace).where(AttendanceWorkplace.is_default))
    assert w is not None
    w.latitude = Decimal(str(WORKPLACE_LAT))
    w.longitude = Decimal(str(WORKPLACE_LNG))
    w.radius_m = 100
    await session.commit()
    return w


# A second workplace ~5 km north of the default one, with its own schedule:
# morning 08:00–12:00, afternoon 13:30–17:00; open 15 min before, absent after 20, check-out
# window 30 min, accuracy 50 m. Its windows: check-in 07:45–08:19 / 13:15–13:49, check-out
# 12:00–12:30 / 17:00–17:30.
BRANCH_METRES_NORTH = 5000


async def make_workplace(
    session: AsyncSession,
    name: str = "Branch 2",
    *,
    metres_north: float = BRANCH_METRES_NORTH,
    radius_m: int = 100,
    morning: tuple[str, str] = ("08:00", "12:00"),
    afternoon: tuple[str, str] = ("13:30", "17:00"),
    open_before_min: int = 15,
    absent_after_min: int = 20,
    checkout_window_min: int = 30,
    max_accuracy_m: int = 50,
    reminders_enabled: bool = True,
    count_early_checkin: bool = True,
    count_overtime: bool = True,
):
    """An active workplace with its own schedule from SCHEDULE_SINCE, every day (committed)."""
    from app.models import AttendanceWorkplace

    w = AttendanceWorkplace(
        name=name,
        latitude=Decimal(str(round(WORKPLACE_LAT + metres_north / METRES_PER_DEGREE_LAT, 6))),
        longitude=Decimal(str(WORKPLACE_LNG)),
        radius_m=radius_m,
    )
    session.add(w)
    await session.flush()
    session.add(
        AttendanceScheduleVersion(
            workplace_id=w.id,
            effective_from=SCHEDULE_SINCE,
            weekdays=[1, 2, 3, 4, 5, 6, 7],
            shifts=[
                {
                    "code": code,
                    "name_km": km,
                    "name_en": en,
                    "start_time": start,
                    "end_time": end,
                    "position": pos,
                }
                for code, (start, end), pos, km, en in (
                    ("morning", morning, 1, "វេនព្រឹក", "Morning shift"),
                    ("afternoon", afternoon, 2, "វេនរសៀល", "Afternoon shift"),
                )
            ],
            open_before_min=open_before_min,
            absent_after_min=absent_after_min,
            checkout_window_min=checkout_window_min,
            max_accuracy_m=max_accuracy_m,
            reminders_enabled=reminders_enabled,
            count_early_checkin=count_early_checkin,
            count_overtime=count_overtime,
        )
    )
    await session.commit()
    return w


async def set_schedule(session: AsyncSession, workplace, **values) -> None:
    """Change every schedule version of `workplace` (rules, `weekdays`, or `shift_times`:
    {code: (start, end)}) and commit."""
    from sqlalchemy import select as _select

    versions = list(
        await session.scalars(
            _select(AttendanceScheduleVersion).where(
                AttendanceScheduleVersion.workplace_id == workplace.id
            )
        )
    )
    times = values.pop("shift_times", None)
    for v in versions:
        for key, value in values.items():
            setattr(v, key, value)
        if times:
            v.shifts = [
                {**s, "start_time": times[s["code"]][0], "end_time": times[s["code"]][1]}
                if s["code"] in times
                else s
                for s in v.shifts
            ]
    await session.commit()


def branch_position(metres_north: float = 0, accuracy_m: float = 15) -> dict:
    """A check-in body `metres_north` of the second workplace (make_workplace's default)."""
    return position(BRANCH_METRES_NORTH + metres_north, accuracy_m)


ATTENDANCE_MINI_APP = "https://app.example.com"


@pytest.fixture
def telegram_bot(monkeypatch):
    """BOT_MODE=webhook with a recording bot on app.state; returns the RecordingSession."""
    from app.bot.runtime import TelegramRuntime
    from app.bot.setup import create_bot, create_dispatcher
    from app.config import get_settings
    from tests.telegram_fakes import RecordingSession

    tg = RecordingSession()
    monkeypatch.setattr(get_settings(), "bot_mode", "webhook")
    monkeypatch.setattr(get_settings(), "mini_app_url", ATTENDANCE_MINI_APP)
    app.state.telegram = TelegramRuntime(
        bot=create_bot(session=tg), dp=create_dispatcher(), secret="s"
    )
    yield tg
    app.state.telegram = None
