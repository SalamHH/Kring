"""The per-place push rules (spec §6.2; D7). Pure functions; the notifier supplies the facts.

A matched event is pushed to a place when ALL hold:
- the event is severe;
- its first message was at most 30 minutes old when the worker first stored it (D7);
- the first message time is inside the place's time window, in the device's tz;
- the place has had fewer than 3 pushes today, the calendar day in the device's tz;
- the place has push on, and the device has a push token.

Time windows are half-open (decided 2026-11-14): 08:00-16:00 includes 08:00 and excludes 16:00.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo


def local(dt: datetime, tz: str) -> datetime:
    return dt.astimezone(ZoneInfo(tz))


def in_window(window: dict[str, Any], first_message_at: datetime, tz: str) -> bool:
    if window.get("all"):
        return True
    t = local(first_message_at, tz)
    return t.isoweekday() in window.get("days", []) and window["from"] <= t.strftime("%H:%M") < window["to"]


def day_bounds(now: datetime, tz: str) -> tuple[datetime, datetime]:
    """Start and end of `now`'s calendar day in tz, as aware datetimes (DST-safe)."""
    z = ZoneInfo(tz)
    d = now.astimezone(z).date()
    start = datetime(d.year, d.month, d.day, tzinfo=z)
    nxt = d + timedelta(days=1)
    return start, datetime(nxt.year, nxt.month, nxt.day, tzinfo=z)


@dataclass(frozen=True)
class Facts:
    severe: bool
    first_message_at: datetime
    ingested_at: datetime
    window: dict[str, Any]
    tz: str
    pushes_today: int
    push_on: bool
    has_token: bool


def why_not(f: Facts, *, max_age_min: int = 30, daily_limit: int = 3) -> str | None:
    """None if the place gets a push; otherwise the first rule that says no (for logs and tests)."""
    if not f.severe:
        return "not severe"
    if f.ingested_at - f.first_message_at > timedelta(minutes=max_age_min):
        return "too old at detection"
    if not f.push_on:
        return "push off"
    if not f.has_token:
        return "no push token"
    if not in_window(f.window, f.first_message_at, f.tz):
        return "outside time window"
    if f.pushes_today >= daily_limit:
        return "daily limit"
    return None
