"""Cached Kartverket lookups backed by the geocode_cache table (spec §9.4).

- Successful lookups are cached, including a genuine «not found» (stored as SQL NULL).
- LookupFailed (429, 5xx, timeouts, connection errors, ...) is never cached: the lookup
  returns None for now and is retried on the next cycle.

Cache keys follow the reference script (adrp|…, adrn|…, sted3|…) so a geocache.json
produced by research/presisjonstest.py could be imported as-is.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.geocode.kartverket import KartverketClient, LookupFailed, Point
from app.geocode.text import norm

log = logging.getLogger(__name__)

_MISS = object()


class GeocodeCache:
    """Key/value access to geocode_cache. The caller owns the connection and its transaction."""

    def __init__(self, conn: AsyncConnection) -> None:
        self.conn = conn

    async def get(self, key: str) -> Any:
        """The cached value (may be None for «not found»), or _MISS if the key is absent."""
        row = (
            await self.conn.execute(text("SELECT value::text FROM geocode_cache WHERE key = :k"), {"k": key})
        ).first()
        if row is None:
            return _MISS
        return None if row[0] is None else json.loads(row[0])

    async def put(self, key: str, value: Any) -> None:
        await self.conn.execute(
            text(
                """
                INSERT INTO geocode_cache (key, value, fetched_at)
                VALUES (:k, CAST(:v AS jsonb), now())
                ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, fetched_at = now()
                """
            ),
            {"k": key, "v": None if value is None else json.dumps(value, ensure_ascii=False)},
        )


class CachedKartverket:
    """Kartverket lookups through the cache. Counts hits, misses and uncached failures."""

    def __init__(self, client: KartverketClient, cache: GeocodeCache) -> None:
        self.client = client
        self.cache = cache
        self.hits = 0
        self.misses = 0
        self.failures = 0

    async def _cached(self, key: str, fetch: Callable[[], Awaitable[Any]]) -> Any:
        value = await self.cache.get(key)
        if value is not _MISS:
            self.hits += 1
            return value
        self.misses += 1
        try:
            value = await fetch()
        except LookupFailed as e:
            self.failures += 1
            log.warning("Kartverket lookup failed, not cached (%s): %s", key, e)
            return None
        await self.cache.put(key, value)
        return value

    async def adresse_punkter(self, navn: str, knr: str) -> list[Point] | None:
        return await self._cached(f"adrp|{knr}|{norm(navn)}", lambda: self.client.adresse_punkter(navn, knr))

    async def adresse_eksakt(self, gate: str, nummer: str, bokstav: str, knr: str) -> dict[str, Any] | None:
        return await self._cached(
            f"adrn|{knr}|{norm(gate)}|{nummer}{bokstav.lower()}",
            lambda: self.client.adresse_eksakt(gate, nummer, bokstav, knr),
        )

    async def stedsnavn(self, navn: str, knr: str) -> dict[str, Any] | None:
        return await self._cached(f"sted3|{knr}|{norm(navn)}", lambda: self.client.stedsnavn(navn, knr))
