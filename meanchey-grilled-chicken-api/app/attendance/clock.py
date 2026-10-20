"""The attendance clock: the only source of "now" for check-in, check-out and the scheduler.

Time always comes from the server (never from the phone). Tests replace `now` with a fixed clock
(`monkeypatch.setattr(clock, "now", ...)`); callers must use `clock.now()`, not import `now`.
"""

from datetime import UTC, datetime


def now() -> datetime:
    return datetime.now(UTC)
