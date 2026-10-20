"""Tracked days and days off, per workplace.

A day is **not tracked** at a workplace when its weekday isn't in that day's schedule version's
`weekdays`, or a holiday covers it (`scope = all`, or `selected` with that workplace). On such a
day nobody is reminded, asked to check in or marked absent.

`Days` holds what that needs for some workplaces over a date range (their versions and the
holidays overlapping the range), so callers ask per (workplace, date) without more queries.
"""

import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.attendance import windows as win
from app.attendance.workplaces import Schedule, default_version, version_on, versions_of
from app.models import (
    AttendanceHoliday,
    AttendanceHolidayWorkplace,
    AttendanceScheduleVersion,
    AttendanceWorkplace,
)

# How far `next_tracked` looks for the next tracked day (a holiday is at most 31 days).
LOOKAHEAD_DAYS = 400


@dataclass(frozen=True)
class HolidaySpan:
    id: uuid.UUID
    name_km: str
    name_en: str
    start: date
    end: date
    scope: str
    workplace_ids: frozenset[uuid.UUID]

    def covers(self, workplace_id: uuid.UUID, day: date) -> bool:
        return self.start <= day <= self.end and (
            self.scope == "all" or workplace_id in self.workplace_ids
        )


@dataclass(frozen=True)
class DayOff:
    """Why a day isn't tracked: a holiday (with its names; wins over the weekday) or the
    weekday."""

    reason: Literal["holiday", "weekday"]
    holidays: tuple[HolidaySpan, ...] = ()


async def holidays_between(session: AsyncSession, start: date, end: date) -> list[HolidaySpan]:
    """Holidays overlapping [start, end], by start date."""
    rows = list(
        await session.scalars(
            select(AttendanceHoliday)
            .where(AttendanceHoliday.start_date <= end, AttendanceHoliday.end_date >= start)
            .order_by(AttendanceHoliday.start_date, AttendanceHoliday.name_en)
        )
    )
    links: dict[uuid.UUID, set[uuid.UUID]] = {}
    if rows:
        for hid, wid in await session.execute(
            select(
                AttendanceHolidayWorkplace.holiday_id, AttendanceHolidayWorkplace.workplace_id
            ).where(AttendanceHolidayWorkplace.holiday_id.in_([h.id for h in rows]))
        ):
            links.setdefault(hid, set()).add(wid)
    return [
        HolidaySpan(
            h.id,
            h.name_km,
            h.name_en,
            h.start_date,
            h.end_date,
            h.scope,
            frozenset(links.get(h.id, ())),
        )
        for h in rows
    ]


@dataclass
class Days:
    workplaces: dict[uuid.UUID, AttendanceWorkplace]
    versions: dict[uuid.UUID, list[AttendanceScheduleVersion]]
    holidays: list[HolidaySpan]
    start: date
    end: date
    _fallback: dict[uuid.UUID, AttendanceScheduleVersion] = field(default_factory=dict)

    def version(self, workplace_id: uuid.UUID, day: date) -> AttendanceScheduleVersion:
        found = version_on(self.versions.get(workplace_id, []), day)
        if found is None:
            # Never expected (bootstrap and create add one): the default schedule, unsaved.
            found = self._fallback.setdefault(workplace_id, default_version(workplace_id, day))
        return found

    def schedule(self, workplace_id: uuid.UUID, day: date) -> Schedule:
        return Schedule(self.workplaces[workplace_id], self.version(workplace_id, day))

    def holidays_on(self, workplace_id: uuid.UUID, day: date) -> tuple[HolidaySpan, ...]:
        return tuple(h for h in self.holidays if h.covers(workplace_id, day))

    def day_off(self, workplace_id: uuid.UUID, day: date) -> DayOff | None:
        holidays = self.holidays_on(workplace_id, day)
        if holidays:
            return DayOff("holiday", holidays)
        if day.isoweekday() not in self.version(workplace_id, day).weekdays:
            return DayOff("weekday")
        return None

    def windows(self, workplace_id: uuid.UUID, day: date) -> list[win.ShiftWindows]:
        """The day's windows, none on a day off."""
        if self.day_off(workplace_id, day) is not None:
            return []
        return self.schedule(workplace_id, day).windows(day)

    def next_tracked(self, workplace_id: uuid.UUID, after: date) -> list[win.ShiftWindows]:
        """The windows of the first tracked day after `after` (within the loaded range)."""
        day = after + timedelta(days=1)
        while day <= self.end:
            windows = self.windows(workplace_id, day)
            if windows:
                return windows
            day += timedelta(days=1)
        return []

    def off_pairs(
        self, workplace_ids: Iterable[uuid.UUID], dates: Iterable[date]
    ) -> set[tuple[uuid.UUID, date]]:
        dates = list(dates)
        return {(w, d) for w in workplace_ids for d in dates if self.day_off(w, d) is not None}


async def load_days(
    session: AsyncSession, workplaces: Sequence[AttendanceWorkplace], start: date, end: date
) -> Days:
    """Versions of `workplaces` and the holidays overlapping [start, end]."""
    ids = [w.id for w in workplaces]
    return Days(
        workplaces={w.id: w for w in workplaces},
        versions=await versions_of(session, ids),
        holidays=await holidays_between(session, start, end),
        start=start,
        end=end,
    )


def date_range(start: date, end: date) -> list[date]:
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]
