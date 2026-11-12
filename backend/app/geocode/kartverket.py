"""Kartverket address and place-name client (spec §9.2, §9.4).

Raw lookups only: no caching here (see app.geocode.cache). Request parameters and response
parsing are ported from research/presisjonstest.py so recorded responses are interchangeable.

Error handling (§9.4, decided 2026-11-12):
- 429, 5xx, timeouts and connection errors are retried at most twice (after 1 s and 2 s),
  then LookupFailed is raised. Callers must not cache it; the next cycle retries.
- 400/404 raise NotFound: a genuine «not found» that address lookups cache as None.
- Any other HTTP error raises LookupFailed without retrying.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable, Sequence
from typing import Any

import httpx

from app.geocode.places import velg_stedsnavn

USER_AGENT = "stedsafe-backend/0.0.1"
MIN_SPACING_S = 0.15
RETRY_DELAYS_S: tuple[float, ...] = (1.0, 2.0)
TIMEOUT_S = 30.0

Point = list[float]  # [lat, lon], rounded to 6 decimals as in the reference script


class LookupFailed(Exception):
    """Transient or unexpected failure. Never cached; retried on the next cycle."""


class NotFound(Exception):
    """HTTP 400/404: the name is invalid or unknown."""


class KartverketClient:
    def __init__(
        self,
        http: httpx.AsyncClient,
        adresse_url: str,
        stedsnavn_urls: Sequence[str],
        *,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        clock: Callable[[], float] = time.monotonic,
        min_spacing_s: float = MIN_SPACING_S,
        retry_delays_s: Sequence[float] = RETRY_DELAYS_S,
    ) -> None:
        self.http = http
        self.adresse_url = adresse_url
        self.stedsnavn_urls = list(stedsnavn_urls)
        self._sleep = sleep
        self._clock = clock
        self._min_spacing_s = min_spacing_s
        self._retry_delays_s = tuple(retry_delays_s)
        self._lock = asyncio.Lock()
        self._last_call: float | None = None
        self.requests = 0  # HTTP requests sent, for logging and tests

    async def _space(self) -> None:
        """Keep ≥ min_spacing_s between request starts, across all callers of this client."""
        async with self._lock:
            if self._last_call is not None:
                wait = self._min_spacing_s - (self._clock() - self._last_call)
                if wait > 0:
                    await self._sleep(wait)
            self._last_call = self._clock()

    async def get_json(self, url: str, params: dict[str, Any]) -> Any:
        attempts = len(self._retry_delays_s) + 1
        for attempt in range(attempts):
            await self._space()
            self.requests += 1
            try:
                resp = await self.http.get(
                    url,
                    params=params,
                    timeout=TIMEOUT_S,
                    headers={"Accept": "application/json", "User-Agent": USER_AGENT},
                )
            except (httpx.TimeoutException, httpx.TransportError) as e:
                reason = f"{type(e).__name__}: {e}"
            else:
                if resp.status_code == 429 or resp.status_code >= 500:
                    reason = f"HTTP {resp.status_code}"
                elif resp.status_code in (400, 404):
                    raise NotFound(f"HTTP {resp.status_code} {url}")
                elif resp.is_error:
                    raise LookupFailed(f"HTTP {resp.status_code} {url}")
                else:
                    try:
                        return resp.json()
                    except ValueError as e:
                        raise LookupFailed(f"invalid JSON from {url}") from e
            if attempt < attempts - 1:
                await self._sleep(self._retry_delays_s[attempt])
        raise LookupFailed(f"{reason} {url} (after {attempts} attempts)")

    async def adresse_punkter(self, navn: str, knr: str) -> list[Point] | None:
        """All address points along a street in a municipality, or None if there are none."""
        try:
            data = await self.get_json(
                self.adresse_url,
                {"adressenavn": navn, "kommunenummer": knr, "treffPerSide": 1000, "utkoordsys": 4258},
            )
        except NotFound:
            return None
        punkter: list[Point] = []
        for a in data.get("adresser", []):
            rp = a.get("representasjonspunkt") or {}
            lat, lon = rp.get("lat"), rp.get("lon")
            if lat is not None and lon is not None:
                punkter.append([round(float(lat), 6), round(float(lon), 6)])
        return punkter or None

    async def adresse_eksakt(self, gate: str, nummer: str, bokstav: str, knr: str) -> dict[str, Any] | None:
        """One exact address (street + number + optional letter); uncertainty 25 m."""
        params: dict[str, Any] = {
            "adressenavn": gate,
            "nummer": nummer,
            "kommunenummer": knr,
            "treffPerSide": 10,
            "utkoordsys": 4258,
        }
        if bokstav:
            params["bokstav"] = bokstav.upper()
        try:
            data = await self.get_json(self.adresse_url, params)
        except NotFound:
            return None
        for a in data.get("adresser", []):
            rp = a.get("representasjonspunkt") or {}
            if rp.get("lat") is not None:
                return {
                    "lat": float(rp["lat"]),
                    "lon": float(rp["lon"]),
                    "usikkerhet_m": 25.0,
                    "kilde": "adresse",
                    "detalj": a.get("adressetekst") or f"{gate} {nummer}",
                }
        return None

    async def stedsnavn(self, navn: str, knr: str) -> dict[str, Any] | None:
        """Place-name lookup (§9.2). URLs are tried in order. As in the reference script, any
        HTTP error (including 404) moves on to the next URL, and if all fail the lookup fails
        rather than being cached as «not found»."""
        params = {"sok": navn, "knr": knr, "utkoordsys": 4258, "treffPerSide": 25, "fuzzy": "false"}
        errors: list[str] = []
        for url in self.stedsnavn_urls:
            try:
                data = await self.get_json(url, params)
            except (LookupFailed, NotFound) as e:
                errors.append(str(e))
                continue
            return velg_stedsnavn(data, navn)
        raise LookupFailed("; ".join(errors) or "no stedsnavn URLs configured")
