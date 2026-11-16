"""Address and place-name search for Nytt sted (spec §8.6 `GET /v1/geocode/search`, F1).

Two Kartverket searches, merged:
- addresses (`adresser/v1/sok`) and place names (`stedsnavn/v1/navn`), both with a trailing `*`
  on the query, since the app searches as the user types and Kartverket matches whole words
  only without it (checked 2026-11-14: «Hølandsg» → 0 hits, «Hølandsg*» → 30);
- ranked by us (decided 2026-11-14), because Kartverket's own order is alphabetical and
  nationwide: «Tøyen*» lists a waterfall in Nittedal before the Tøyen area in Oslo.
  - Place names: exact name first, then places in the ingested fylker, then area types
    before others (the geocoder's STEDSTYPE_PRIORITET), then Kartverket's order.
  - Addresses: the query's house number exactly («Hølandsgata 1» → 1A, 1B before 10, 14),
    then in the ingested fylker, then street, number and letter.
  - A query with a digit lists addresses first; otherwise place names first.
- The secondary line is the municipality, with the postcode for addresses and the place type
  for place names. Kartverket's search APIs return no bydel.

Each source is cached in geocode_cache per normalised query, for search_cache_max_age_days.
A failed Kartverket call is never cached (§9.4), and the request fails with 502.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass
from typing import Any

from app.geocode.cache import MISS, GeocodeCache
from app.geocode.kartverket import KartverketClient
from app.geocode.places import STEDSTYPE_PRIORITET, UKJENT_PRIORITET
from app.geocode.text import norm

PER_SOURCE = 10  # hits asked of each source, before ranking
MAX_RESULTS = 10


@dataclass(frozen=True)
class SearchResult:
    kind: str  # "adresse" | "sted"
    label: str
    secondary: str
    lat: float
    lon: float
    kommunenummer: str | None


def _title(s: str | None) -> str:
    """Kartverket's address API writes municipality and post-town names in capitals («OSLO»)."""
    s = (s or "").strip()
    return s.title() if s.isupper() else s


def _wildcard(q: str) -> str:
    q = " ".join(q.split())
    return q if q.endswith("*") else q + "*"


def _query_number(q: str) -> int | None:
    m = re.search(r"(\d+)\s*[A-Za-zÆØÅæøå]?\s*$", q)
    return int(m.group(1)) if m else None


def parse_adresser(data: dict[str, Any], q: str, covered: Callable[[str | None], bool]) -> list[SearchResult]:
    want = _query_number(q)
    ranked: list[tuple[tuple[Any, ...], SearchResult]] = []
    for i, a in enumerate(data.get("adresser") or []):
        if not isinstance(a, dict):
            continue
        rp = a.get("representasjonspunkt") or {}
        lat, lon = rp.get("lat"), rp.get("lon")
        tekst = a.get("adressetekst")
        if lat is None or lon is None or not tekst:
            continue
        knr = a.get("kommunenummer") or None
        kommune = _title(a.get("kommunenavn"))
        poststed = _title(a.get("poststed"))
        post = " ".join(x for x in (a.get("postnummer"), poststed) if x)
        secondary = post if poststed == kommune or not kommune else ", ".join(x for x in (post, kommune) if x)
        nummer = a.get("nummer")
        key = (
            not (want is not None and nummer == want),
            not covered(knr),
            norm(a.get("adressenavn")),
            nummer if isinstance(nummer, int) else 10**9,
            a.get("bokstav") or "",
            i,
        )
        ranked.append((key, SearchResult("adresse", tekst, secondary, float(lat), float(lon), knr)))
    return [r for _, r in sorted(ranked, key=lambda x: x[0])]


def parse_stedsnavn(
    data: dict[str, Any], q: str, covered: Callable[[str | None], bool]
) -> list[SearchResult]:
    want = norm(q.rstrip("*"))
    ranked: list[tuple[tuple[Any, ...], SearchResult]] = []
    seen: set[tuple[str, str | None, str]] = set()
    for i, n in enumerate(data.get("navn") or []):
        if not isinstance(n, dict) or not n.get("skrivemåte"):
            continue
        rp = n.get("representasjonspunkt") or {}
        lat = rp.get("nord", rp.get("lat"))
        lon = rp.get("øst", rp.get("ost", rp.get("lon")))
        if lat is None or lon is None:
            continue
        kommuner = [k for k in n.get("kommuner") or [] if isinstance(k, dict)]
        knr = kommuner[0].get("kommunenummer") if kommuner else None
        kommune = kommuner[0].get("kommunenavn", "") if kommuner else ""
        typ = n.get("navneobjekttype") or ""
        label = n["skrivemåte"]
        if (norm(label), knr, typ) in seen:
            continue
        seen.add((norm(label), knr, typ))
        secondary = ", ".join(x for x in (typ, kommune) if x)
        key = (
            norm(label) != want,
            not covered(knr),
            STEDSTYPE_PRIORITET.get(norm(typ), UKJENT_PRIORITET),
            i,
        )
        ranked.append((key, SearchResult("sted", label, secondary, float(lat), float(lon), knr)))
    return [r for _, r in sorted(ranked, key=lambda x: x[0])]


async def _cached(
    cache: GeocodeCache, key: str, max_age_days: int, fetch: Callable[[], Awaitable[list[SearchResult]]]
) -> list[SearchResult]:
    value = await cache.get(key, max_age_days)
    if value is not MISS:
        return [SearchResult(**r) for r in value or []]
    results = await fetch()  # LookupFailed propagates: nothing is cached
    await cache.put(key, [asdict(r) for r in results])
    return results


async def search(
    client: KartverketClient,
    cache: GeocodeCache,
    q: str,
    covered: Callable[[str | None], bool],
    max_age_days: int,
) -> list[SearchResult]:
    q = " ".join(q.split())
    sok = _wildcard(q)
    nq = norm(q)

    async def adresser() -> list[SearchResult]:
        return parse_adresser(await client.sok_adresser(sok, PER_SOURCE), q, covered)

    async def steder() -> list[SearchResult]:
        return parse_stedsnavn(await client.sok_stedsnavn(sok, PER_SOURCE), q, covered)

    # One after the other: the client spaces its requests anyway, and the cache shares one
    # connection, which can't run two queries at once.
    a = await _cached(cache, f"sok|adr|{nq}", max_age_days, adresser)
    s = await _cached(cache, f"sok|sted|{nq}", max_age_days, steder)
    merged = a + s if any(c.isdigit() for c in q) else s + a
    return merged[:MAX_RESULTS]


async def kommune_for_punkt(
    client: KartverketClient, cache: GeocodeCache, lat: float, lon: float
) -> str | None:
    """The kommunenummer of the point, or None if it lies in no municipality. Cached per point
    rounded to 5 decimals (about 1 m), including «none». LookupFailed propagates, uncached."""
    key = f"kpkt|{lat:.5f}|{lon:.5f}"
    value = await cache.get(key)
    if value is not MISS:
        return value
    data = await client.kommune_for_punkt(round(lat, 5), round(lon, 5))
    knr = data.get("kommunenummer") if data else None
    await cache.put(key, knr)
    return knr
