"""GET /v1/geocode/search?q= (§8.6): Kartverket address and place-name search, merged, cached
and rate limited. See app.geocode.search for the ranking."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel

from app.api.deps import CurrentDevice, Session
from app.api.errors import ApiError
from app.api.ratelimit import retry_after_header
from app.geocode.cache import GeocodeCache
from app.geocode.kartverket import LookupFailed
from app.geocode.search import search

router = APIRouter(prefix="/v1/geocode", tags=["geocode"])


class Result(BaseModel):
    kind: Literal["adresse", "sted"]
    label: str
    secondary: str
    lat: float
    lon: float
    kommunenummer: str | None
    covered: bool  # inside the ingested fylker (D9)


@router.get("/search", response_model=list[Result])
async def geocode_search(
    request: Request,
    device: CurrentDevice,
    session: Session,
    q: Annotated[str, Query(min_length=2, max_length=100)],
) -> list[Result]:
    q = q.strip()
    if len(q.rstrip("*")) < 2:
        raise ApiError(422, "invalid_request", "q must have at least 2 characters")
    wait = request.app.state.search_limiter.hit(str(device.id))
    if wait is not None:
        raise ApiError(
            429, "rate_limited", "Too many searches", headers={"Retry-After": retry_after_header(wait)}
        )
    settings = request.app.state.settings
    try:
        results = await search(
            request.app.state.kartverket,
            GeocodeCache(await session.connection()),
            q,
            settings.kommune_allowed,
            settings.search_cache_max_age_days,
        )
    except LookupFailed as e:
        raise ApiError(502, "kartverket_unavailable", "Kartverket did not answer; try again") from e
    return [
        Result(
            kind=r.kind,  # type: ignore[arg-type]
            label=r.label,
            secondary=r.secondary,
            lat=r.lat,
            lon=r.lon,
            kommunenummer=r.kommunenummer,
            covered=settings.kommune_allowed(r.kommunenummer),
        )
        for r in results
    ]
