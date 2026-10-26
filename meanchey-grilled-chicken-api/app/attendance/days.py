"""Tracked days and days off, per workplace and per employee.

A day is **not tracked** at a workplace when its weekday isn't in that day's schedule version's
`weekdays`, or a holiday covers it (`scope = all`, or `selected` with that workplace). On such a
day nobody is reminded, asked to check in or marked absent.

`Days` holds what that needs for some workplaces over a date range (their versions and the
holidays overlapping the range), so callers ask per (workplace, date) without more queries.

It is also **the resolver of each employee's schedule** (`Days.resolve`, loaded with
`user_ids`): the workplace's version for the date, then the employee's override version (only
the fields set), then a holiday exception for that date (`app.attendance.personal`). Everything
that needs "who must work when" asks it with the employee's id: check-in / check-out,
`me/today`, the scheduler, the day view, the summaries. Without a user id it answers for the
workplace alone (the calendar, the holiday diffs). Whether the employee is tracked at all
(start date, untracked periods) is `app.attendance.tracking`, asked first by the callers.
"""

import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.attendance import personal as per
from app.attendance import windows as win
from app.attendance.workplaces import Schedule, default_version, version_on, versions_of
from app.config import get_settings
from app.models import (
    AttendanceEmployeeOverride,
    AttendanceHoliday,
    AttendanceHolidayException,
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


@dataclass(frozen=True)
class Resolved:
    """One employee's (or, without one, the workplace's) day: the shifts to work (none on a day
    off) with the workplace's rules."""

    workplace_id: uuid.UUID
    day: date
    defs: list[win.ShiftDef]
    rules: win.Rules
    weekdays: list[int]
    day_off: DayOff | None
    # The employee's shifts on a working day, whatever the weekday or holiday.
    normal: list[win.ShiftDef]
    override: AttendanceEmployeeOverride | None = None
    exception: AttendanceHolidayException | None = None

    @property
    def custom(self) -> list[per.Field]:
        return per.custom_fields(self.override)

    def windows(self) -> list[win.ShiftWindows]:
        return win.day_windows(self.defs, self.rules, self.day, get_settings().business_tz)


@dataclass
class Days:
    workplaces: dict[uuid.UUID, AttendanceWorkplace]
    versions: dict[uuid.UUID, list[AttendanceScheduleVersion]]
    holidays: list[HolidaySpan]
    start: date
    end: date
    # Per employee (loaded with `user_ids`): override versions oldest first, and holiday
    # exceptions by date.
    overrides: dict[uuid.UUID, list[AttendanceEmployeeOverride]] = field(default_factory=dict)
    exceptions: dict[tuple[uuid.UUID, date], AttendanceHolidayException] = field(
        default_factory=dict
    )
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

    def resolve(
        self, workplace_id: uuid.UUID, day: date, user_id: uuid.UUID | None = None
    ) -> Resolved:
        """The day of `user_id` at `workplace_id` (without a user: the workplace's own)."""
        schedule = self.schedule(workplace_id, day)
        base, rules = schedule.defs, schedule.rules
        o = per.override_on(self.overrides.get(user_id, []), day) if user_id else None
        weekdays = sorted(o.weekdays if o and o.weekdays is not None else schedule.weekdays)
        normal = per.personal_defs(base, o)

        def done(defs: list[win.ShiftDef], off: DayOff | None, **kw: Any) -> Resolved:
            return Resolved(workplace_id, day, defs, rules, weekdays, off, normal, o, **kw)

        holidays = self.holidays_on(workplace_id, day)
        if holidays:
            e = self.exceptions.get((user_id, day)) if user_id else None
            if e is None:
                return done([], DayOff("holiday", holidays))
            defs = per.exception_defs(normal, base, e)
            tz = get_settings().business_tz
            if e.created_at is not None and e.created_at.astimezone(tz).date() == day:
                # Set on the day itself: only the shifts that hadn't opened yet.
                opened = {d.code for d in per.opened_before(defs, rules, day, e.created_at, tz)}
                defs = [d for d in defs if d.code not in opened]
            if not defs:
                return done([], DayOff("holiday", holidays), exception=e)
            return done(defs, None, exception=e)
        # A version effective on the day it was saved: the shifts already open then keep the
        # previous setting that day (`{code: times}`, or null: not worked that day).
        kept_map = o.kept_shifts if o is not None and o.effective_from == day else None
        kept_map = kept_map or {}
        kept = [per.with_times(d, kept_map) for d in base if kept_map.get(d.code)]
        if day.isoweekday() not in weekdays:
            return done(kept, None if kept else DayOff("weekday"))
        by_code = {d.code: d for d in kept}
        defs = [by_code.pop(d.code, d) for d in normal if d.code not in kept_map]
        defs += list(by_code.values())
        return done(sorted(defs, key=lambda d: d.position), None)

    def day_off(
        self, workplace_id: uuid.UUID, day: date, user_id: uuid.UUID | None = None
    ) -> DayOff | None:
        return self.resolve(workplace_id, day, user_id).day_off

    def windows(
        self, workplace_id: uuid.UUID, day: date, user_id: uuid.UUID | None = None
    ) -> list[win.ShiftWindows]:
        """The day's windows, none on a day off."""
        return self.resolve(workplace_id, day, user_id).windows()

    def next_tracked(
        self, workplace_id: uuid.UUID, after: date, user_id: uuid.UUID | None = None
    ) -> list[win.ShiftWindows]:
        """The windows of the first tracked day after `after` (within the loaded range)."""
        day = after + timedelta(days=1)
        while day <= self.end:
            windows = self.windows(workplace_id, day, user_id)
            if windows:
                return windows
            day += timedelta(days=1)
        return []

    def personal_ids(self, day: date) -> set[uuid.UUID]:
        """Employees whose day may differ from their workplace's: an override version in effect
        on `day`, or a holiday exception on it."""
        ids = {u for u, vs in self.overrides.items() if per.override_on(vs, day) is not None}
        return ids | {u for (u, d) in self.exceptions if d == day}

    def off_pairs(
        self, workplace_ids: Iterable[uuid.UUID], dates: Iterable[date]
    ) -> set[tuple[uuid.UUID, date]]:
        dates = list(dates)
        return {(w, d) for w in workplace_ids for d in dates if self.day_off(w, d) is not None}


async def personal_of(
    session: AsyncSession, user_ids: Iterable[uuid.UUID] | Literal["all"], start: date, end: date
) -> tuple[
    dict[uuid.UUID, list[AttendanceEmployeeOverride]],
    dict[tuple[uuid.UUID, date], AttendanceHolidayException],
]:
    """Override versions up to `end` (oldest first) and holiday exceptions in [start, end] of
    some employees (or everyone)."""
    o_stmt = (
        select(AttendanceEmployeeOverride)
        .where(AttendanceEmployeeOverride.effective_from <= end)
        .order_by(AttendanceEmployeeOverride.effective_from)
    )
    e_stmt = select(AttendanceHolidayException).where(
        AttendanceHolidayException.day >= start, AttendanceHolidayException.day <= end
    )
    if user_ids != "all":
        ids = list(user_ids)
        if not ids:
            return {}, {}
        o_stmt = o_stmt.where(AttendanceEmployeeOverride.user_id.in_(ids))
        e_stmt = e_stmt.where(AttendanceHolidayException.user_id.in_(ids))
    overrides: dict[uuid.UUID, list[AttendanceEmployeeOverride]] = {}
    for o in await session.scalars(o_stmt):
        overrides.setdefault(o.user_id, []).append(o)
    exceptions = {(e.user_id, e.day): e for e in await session.scalars(e_stmt)}
    return overrides, exceptions


async def load_days(
    session: AsyncSession,
    workplaces: Sequence[AttendanceWorkplace],
    start: date,
    end: date,
    user_ids: Iterable[uuid.UUID] | Literal["all"] = (),
) -> Days:
    """Versions of `workplaces` and the holidays overlapping [start, end]; with `user_ids` also
    those employees' overrides and holiday exceptions (`"all"`: everyone's)."""
    ids = [w.id for w in workplaces]
    overrides, exceptions = await personal_of(session, user_ids, start, end)
    return Days(
        workplaces={w.id: w for w in workplaces},
        versions=await versions_of(session, ids),
        holidays=await holidays_between(session, start, end),
        start=start,
        end=end,
        overrides=overrides,
        exceptions=exceptions,
    )


def date_range(start: date, end: date) -> list[date]:
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]
