"""Protection-check service level (ADR 0004): pure arithmetic, no I/O.

A *protection check* is one successful run of scripts/protection_monitor.py
against live broker state. The service level: while the exchange is open, the
newest protection check is never older than MAX_DELAY. Monitoring is *stale*
whenever that bound is exceeded. The heartbeat measures it from the GitHub
Actions run history (completion time of successful protection-monitor runs).

MAX_DELAY is three 30-minute cron slots: it tolerates two consecutive dropped
slots and is the smallest bound that distinguishes "the scheduler hiccuped"
from "nothing is watching". Research 0008 shows GitHub's cron does not meet
it (first run of the day lands ~5 h after the open); the number is the target
the deployed scheduler must be measured against, not a description of it.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

EXCHANGE_TZ = ZoneInfo("America/New_York")
SESSION_OPEN = time(9, 30)
SESSION_CLOSE = time(16, 0)
MAX_DELAY = timedelta(minutes=90)


def _aware(stamp: datetime, what: str) -> datetime:
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise ValueError(f"{what} must be timezone-aware: {stamp!r}")
    return stamp


def session_window(day: date) -> tuple[datetime, datetime]:
    """Regular-session open and close of `day` as aware UTC datetimes."""
    open_ = datetime.combine(day, SESSION_OPEN, tzinfo=EXCHANGE_TZ)
    close = datetime.combine(day, SESSION_CLOSE, tzinfo=EXCHANGE_TZ)
    return open_.astimezone(ZoneInfo("UTC")), close.astimezone(ZoneInfo("UTC"))


def staleness_breaches(checks: list[datetime], day: date, now: datetime,
                       max_delay: timedelta = MAX_DELAY) -> list[dict]:
    """Intervals inside `day`'s session (up to `now`) during which the newest
    protection check was older than `max_delay`. `checks` are completion
    times of successful checks, aware, ascending. Each interval is reported
    as ISO-8601 UTC bounds plus its length in whole minutes."""
    _aware(now, "now")
    stamps = [_aware(c, "check") for c in checks]
    if stamps != sorted(stamps):
        raise ValueError("checks must be in ascending order")
    open_, close = session_window(day)
    end = min(close, now)
    if end <= open_:
        return []
    breaches: list[dict] = []
    # Boundaries where the "age of newest check" curve can cross max_delay:
    # each check resets the age to zero; it becomes stale max_delay later.
    last_check = max((c for c in stamps if c < open_), default=None)
    stale_from = (last_check + max_delay) if last_check else open_
    cursor = open_
    for c in [c for c in stamps if open_ <= c < end] + [end]:
        start = max(stale_from, cursor)
        if start < c:
            breaches.append({"from": start.isoformat(), "to": c.isoformat(),
                             "minutes": int((c - start).total_seconds() // 60)})
        cursor = c
        stale_from = c + max_delay
    return breaches
