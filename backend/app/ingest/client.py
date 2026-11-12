"""Politiloggen fetching (spec §8.3): one page with backoff, the time window, and the paging
stop rule.

- 429, 5xx, timeouts and connection errors are retried after 1, 2, 4, 8 and 16 s, then the
  poll fails (PollFailed). Other HTTP errors and a malformed payload fail at once.
- Window (decided 2026-11-12): LastDay, or LastQuarter when there has been no successful poll
  for more than `wide_window_after_s` (or never).
- Stop rule (decided 2026-11-12): read at least `min_pages` pages, paginating by
  `skip += len(page)`. After that, continue only while a page still has a thread whose last
  message is newer than the last successful poll minus the safety margin. Always stop at
  hasMoreResults=false or an empty page.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import httpx

from app.geocode.kartverket import USER_AGENT
from app.ingest.politiloggen import Page, Thread, parse_page
from app.settings import Settings

log = logging.getLogger(__name__)

BACKOFF_S: tuple[float, ...] = (1.0, 2.0, 4.0, 8.0, 16.0)
PAGE_SPACING_S = 0.2  # pause between pages, as in the reference script
TIMEOUT_S = 30.0


class PollFailed(Exception):
    """A page could not be fetched or parsed; the cycle is not a successful poll."""


class PolitiloggenClient:
    def __init__(
        self,
        http: httpx.AsyncClient,
        url: str,
        *,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        backoff_s: Sequence[float] = BACKOFF_S,
    ) -> None:
        self.http = http
        self.url = url
        self._sleep = sleep
        self._backoff_s = tuple(backoff_s)
        self.requests = 0

    async def fetch_page(self, time_span: str, skip: int, take: int) -> Page:
        params = {"take": take, "skip": skip, "sortByEnum": "LastMessageOn", "timeSpanType": time_span}
        attempts = len(self._backoff_s) + 1
        reason = ""
        for attempt in range(attempts):
            self.requests += 1
            try:
                resp = await self.http.get(
                    self.url,
                    params=params,
                    timeout=TIMEOUT_S,
                    headers={"Accept": "application/json", "User-Agent": USER_AGENT},
                )
            except (httpx.TimeoutException, httpx.TransportError) as e:
                reason = f"{type(e).__name__}: {e}"
            else:
                if resp.status_code == 429 or resp.status_code >= 500:
                    reason = f"HTTP {resp.status_code}"
                elif resp.is_error:
                    raise PollFailed(f"Politiloggen HTTP {resp.status_code}")
                else:
                    try:
                        payload = resp.json()
                    except ValueError as e:
                        raise PollFailed("Politiloggen sent invalid JSON") from e
                    page = parse_page(payload)
                    if page.malformed:
                        raise PollFailed("Politiloggen sent a payload of the wrong shape")
                    return page
            if attempt < attempts - 1:
                delay = self._backoff_s[attempt]
                log.warning("Politiloggen %s, retrying in %.0f s", reason, delay)
                await self._sleep(delay)
        raise PollFailed(f"Politiloggen {reason} (after {attempts} attempts)")


def choose_time_span(settings: Settings, last_success: datetime | None, now: datetime) -> str:
    if last_success is None or now - last_success > timedelta(seconds=settings.wide_window_after_s):
        return settings.politiloggen_wide_time_span
    return settings.politiloggen_time_span


@dataclass
class Window:
    time_span: str
    threads: list[Thread] = field(default_factory=list)  # deduplicated, first occurrence wins
    pages: int = 0
    skipped: int = 0  # threads that could not be parsed


async def fetch_window(
    client: PolitiloggenClient,
    settings: Settings,
    last_success: datetime | None,
    now: datetime,
    *,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> Window:
    """All pages the stop rule asks for. Raises PollFailed if any page fails."""
    window = Window(choose_time_span(settings, last_success, now))
    since = None if last_success is None else last_success - timedelta(seconds=settings.poll_safety_margin_s)
    seen: set[str] = set()
    skip = 0
    while True:
        if window.pages:
            await sleep(PAGE_SPACING_S)
        page = await client.fetch_page(window.time_span, skip, settings.page_size)
        window.pages += 1
        window.skipped += page.skipped
        for t in page.threads:
            if t.id not in seen:
                seen.add(t.id)
                window.threads.append(t)
        if page.size == 0 or not page.has_more:
            break
        if window.pages >= settings.min_pages and since is not None:
            if not any(t.last_message_at > since for t in page.threads):
                break
        skip += page.size
    return window
