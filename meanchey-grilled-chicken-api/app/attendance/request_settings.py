"""The request deadline day (attendance settings): stored in `app_settings`, default 7."""

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.attendance.requests import DEADLINE_DAY_MAX, DEADLINE_DAY_MIN, DEFAULT_DEADLINE_DAY
from app.models import AppSetting, utcnow

DEADLINE_KEY = "attendance.request_deadline_day"
REMINDER_KEY = "attendance.request_reminder_month"  # "2026-10": the last month reminded


async def get_deadline_day(session: AsyncSession) -> int:
    row = await session.get(AppSetting, DEADLINE_KEY)
    try:
        value = int(row.value) if row is not None else DEFAULT_DEADLINE_DAY
    except ValueError:
        return DEFAULT_DEADLINE_DAY
    return value if DEADLINE_DAY_MIN <= value <= DEADLINE_DAY_MAX else DEFAULT_DEADLINE_DAY


async def set_deadline_day(session: AsyncSession, value: int) -> None:
    await session.execute(
        pg_insert(AppSetting)
        .values(key=DEADLINE_KEY, value=str(value))
        .on_conflict_do_update(
            index_elements=[AppSetting.key], set_={"value": str(value), "updated_at": utcnow()}
        )
    )


async def get_marker(session: AsyncSession) -> str | None:
    row = await session.get(AppSetting, REMINDER_KEY)
    return row.value if row is not None else None


async def set_marker(session: AsyncSession, value: str) -> None:
    await session.execute(
        pg_insert(AppSetting)
        .values(key=REMINDER_KEY, value=value)
        .on_conflict_do_update(
            index_elements=[AppSetting.key], set_={"value": value, "updated_at": utcnow()}
        )
    )
