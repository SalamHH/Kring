"""Municipality name → kommunenummer, and the allowed-set filter (spec §8.3).

Names come from Kartverket's kommuneinfo API (`/kommuneinfo/v1/kommuner`), cached in
geocode_cache under KEY. A failed fetch is never cached: with a stale cached copy we keep
using it; with none, KommuneinfoFailed is raised and the caller retries next cycle.

Politiloggen sometimes puts a police district in the municipality field ("Oslo politidistrikt").
Such names, and names shared by two municipalities (Våler, Herøy), do not resolve: the thread
is skipped and a WARN is logged once per name per process.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.geocode.cache import GeocodeCache
from app.geocode.kartverket import USER_AGENT
from app.geocode.text import norm
from app.ingest.politiloggen import Thread

log = logging.getLogger(__name__)

KEY = "kommuner|v1"
MAX_AGE = timedelta(days=30)


class KommuneinfoFailed(Exception):
    """kommuneinfo could not be fetched and nothing is cached."""


@dataclass(frozen=True)
class Kommune:
    nummer: str
    navn: str  # Norwegian name, used as the geocoder's municipality name


class KommuneRegister:
    def __init__(self, rows: Iterable[dict[str, Any]]) -> None:
        by_name: dict[str, set[tuple[str, str]]] = {}
        for r in rows:
            if not isinstance(r, dict):
                continue
            nr = str(r.get("kommunenummer") or "").strip()
            navn_no = str(r.get("kommunenavnNorsk") or r.get("kommunenavn") or "").strip()
            if len(nr) != 4 or not nr.isdigit() or not navn_no:
                continue
            for n in {r.get("kommunenavn"), r.get("kommunenavnNorsk")}:
                if isinstance(n, str) and n.strip():
                    by_name.setdefault(norm(n), set()).add((nr, navn_no))
        self._unique = {k: Kommune(*next(iter(v))) for k, v in by_name.items() if len(v) == 1}
        self._ambiguous = {k for k, v in by_name.items() if len(v) > 1}
        self._warned: set[str] = set()

    def __len__(self) -> int:
        return len(self._unique)

    def resolve(self, name: str | None) -> Kommune | None:
        """The municipality for a Politiloggen name, or None (WARN once per name)."""
        key = norm(name or "")
        k = self._unique.get(key)
        if k is None and key not in self._warned:
            self._warned.add(key)
            why = "ambiguous" if key in self._ambiguous else "unknown"
            log.warning("Politiloggen: %s municipality %r, threads skipped", why, name)
        return k


@dataclass(frozen=True)
class ScopedThread:
    thread: Thread
    kommune: Kommune


def in_scope(
    threads: Iterable[Thread], register: KommuneRegister, allowed_fylker: Iterable[str]
) -> list[ScopedThread]:
    """Threads whose municipality resolves to an allowed fylke (first two digits of knr)."""
    allowed = set(allowed_fylker)
    out: list[ScopedThread] = []
    for t in threads:
        k = register.resolve(t.municipality)
        if k is not None and k.nummer[:2] in allowed:
            out.append(ScopedThread(t, k))
    return out


async def fetch_kommuner(http: httpx.AsyncClient, url: str) -> list[dict[str, Any]]:
    resp = await http.get(url, timeout=30.0, headers={"Accept": "application/json", "User-Agent": USER_AGENT})
    resp.raise_for_status()
    data = resp.json()
    if not isinstance(data, list) or not data:
        raise ValueError("kommuneinfo: expected a non-empty list")
    return data


async def load_register(
    conn: AsyncConnection, http: httpx.AsyncClient, url: str, *, now: datetime | None = None
) -> KommuneRegister:
    """The register from the cache, refreshed from kommuneinfo when older than MAX_AGE."""
    now = now or datetime.now(UTC)
    row = (
        await conn.execute(text("SELECT value, fetched_at FROM geocode_cache WHERE key = :k"), {"k": KEY})
    ).first()
    cached: list[dict[str, Any]] | None = row[0] if row and isinstance(row[0], list) else None
    if cached and row and row[1] and now - row[1] < MAX_AGE:
        return KommuneRegister(cached)
    try:
        rows = await fetch_kommuner(http, url)
    except (httpx.HTTPError, ValueError) as e:
        if cached:
            log.warning("kommuneinfo refresh failed, using cached copy: %s", e)
            return KommuneRegister(cached)
        raise KommuneinfoFailed(str(e)) from e
    register = KommuneRegister(rows)
    if len(register) == 0:
        raise KommuneinfoFailed("kommuneinfo returned no usable rows")
    await GeocodeCache(conn).put(KEY, rows)
    return register
