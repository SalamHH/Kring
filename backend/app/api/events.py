"""Preview and event endpoints (§8.6; F3, F4, F5, F10; D1, D2, D5).

- `GET /v1/preview`: counts for a circle that isn't saved yet (Nytt sted).
- `GET /v1/places/{id}/events`: what a place card and its list show.
- `GET /v1/events/{id}`: Hendelse, optionally relative to one of the device's places.
- `POST /v1/events/{id}/feedback`: «Feil plassering?».
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Query, Response
from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.api.deps import CurrentDevice, Session
from app.api.errors import ApiError
from app.match.categories import app_category, canonical
from app.match.rules import (
    IMPRECISE_NEARBY,
    MATCH,
    Circle,
    events_near,
    hidden_traffic_count,
    municipality_only_count,
)
from app.match.title import district_name, title

router = APIRouter(prefix="/v1", tags=["events"])

Relation = Literal["match", "imprecise_nearby"]
PREVIEW_DAYS = 30
NOTICE_HOURS = 24  # D2: district notices are shown for 24 h


async def _since(conn: AsyncConnection, days: int) -> datetime:
    return (await conn.execute(text("SELECT now() - make_interval(days => :d)"), {"d": days})).scalar_one()


def _title(row: Any) -> str:
    return title(
        category=row.category,
        scope=row.scope,
        geocode_method=row.geocode_method,
        geocode_match=row.geocode_match,
        area=row.area,
        municipality=row.municipality,
        district=row.district,
    )


# --- preview -------------------------------------------------------------------------------


class Preview(BaseModel):
    days: int
    matched: int
    severe: int  # of the matched
    hidden_traffic: int  # Trafikk events that would match, when Trafikk is off
    imprecise_nearby: int


def _parse_categories(raw: list[str]) -> list[str]:
    # Repeated (?categories=Vold&categories=Brann) or comma-separated (?categories=Vold,Brann).
    items = [c.strip() for r in raw for c in r.split(",") if c.strip()]
    try:
        cats = canonical(items)
    except ValueError as e:
        raise ApiError(422, "invalid_request", str(e)) from e
    if not cats:
        raise ApiError(422, "invalid_request", "at least one category")
    return cats


@router.get("/preview", response_model=Preview)
async def preview(
    device: CurrentDevice,
    session: Session,
    lat: Annotated[float, Query(ge=-90, le=90)],
    lon: Annotated[float, Query(ge=-180, le=180)],
    radius_m: Annotated[int, Query(ge=300, le=2000, multiple_of=100)],
    categories: Annotated[list[str], Query()],
) -> Preview:
    cats = _parse_categories(categories)
    conn = await session.connection()
    since = await _since(conn, PREVIEW_DAYS)
    circle = Circle(lat, lon, radius_m)
    near = await events_near(conn, circle, cats, since)
    matched = [r for r in near if r.relation == MATCH]
    return Preview(
        days=PREVIEW_DAYS,
        matched=len(matched),
        severe=sum(1 for r in matched if r.severity == "severe"),
        hidden_traffic=await hidden_traffic_count(conn, circle, cats, since),
        imprecise_nearby=sum(1 for r in near if r.relation == IMPRECISE_NEARBY),
    )


# --- a place's events ----------------------------------------------------------------------


class EventSummary(BaseModel):
    id: str
    title: str
    category: str  # app category (Appendix B)
    police_category: str
    severity: Literal["severe", "normal"]
    first_message_at: datetime
    last_message_at: datetime
    is_active: bool | None
    area: str | None
    municipality: str | None
    lat: float
    lon: float
    uncertainty_m: int | None
    precision_tier: Literal["gate", "nabolag", "bydel"]
    geocode_method: str | None
    distance_m: int
    relation: Relation
    pushed: bool  # this place got a push for it


class Notice(BaseModel):
    id: str
    title: str
    category: str
    police_category: str
    district: str
    first_message_at: datetime
    last_message_at: datetime
    is_active: bool | None


class PlaceEvents(BaseModel):
    place_id: uuid.UUID
    days: int
    events: list[EventSummary]
    municipality_only: int  # D1: events in the place's municipality with no point; counted only
    district_notices: list[Notice]  # D2: from the last 24 h, for the place's police district


async def _place(session: Session, device_id: uuid.UUID, place_id: uuid.UUID) -> Any:
    row = (
        await session.execute(
            text("""
                SELECT id, ST_Y(center::geometry) AS lat, ST_X(center::geometry) AS lon, radius_m,
                       categories, kommunenummer
                FROM places WHERE id = :id AND device_id = :d
            """),
            {"id": place_id, "d": device_id},
        )
    ).one_or_none()
    if row is None:
        raise ApiError(404, "not_found", "No such place")
    return row


async def _pushed(conn: AsyncConnection, place_id: uuid.UUID, event_ids: list[str]) -> set[str]:
    if not event_ids:
        return set()
    rows = await conn.execute(
        text(
            "SELECT event_id FROM notifications "
            "WHERE place_id = :p AND kind = 'push' AND event_id = ANY(:ids)"
        ),
        {"p": place_id, "ids": event_ids},
    )
    return {r[0] for r in rows}


async def _notices(conn: AsyncConnection, kommunenummer: str | None) -> list[Notice]:
    """District-wide notices from the last 24 h, for every police district that covers the
    place's municipality (read from the stored events, as in step 2)."""
    if not kommunenummer:
        return []
    rows = await conn.execute(
        text("""
            SELECT n.id, n.category, n.district, n.municipality, n.scope, n.first_message_at,
                   n.last_message_at, n.is_active, n.area, n.geocode_method, n.geocode_match
            FROM events n
            WHERE n.scope = 'distrikt'
              AND n.last_message_at >= now() - make_interval(hours => :h)
              AND lower(n.district) IN (
                SELECT DISTINCT lower(e.district) FROM events e
                WHERE e.scope = 'kommune' AND e.kommunenummer = :knr AND e.district IS NOT NULL
              )
            ORDER BY n.first_message_at DESC, n.id
        """),
        {"knr": kommunenummer, "h": NOTICE_HOURS},
    )
    return [
        Notice(
            id=r.id,
            title=_title(r),
            category=app_category(r.category),
            police_category=r.category,
            district=district_name(r.district or r.municipality),
            first_message_at=r.first_message_at,
            last_message_at=r.last_message_at,
            is_active=r.is_active,
        )
        for r in rows
    ]


def _summary(r: Any, pushed: set[str]) -> EventSummary:
    return EventSummary(
        id=r.id,
        title=_title(r),
        category=app_category(r.category),
        police_category=r.category,
        severity=r.severity,
        first_message_at=r.first_message_at,
        last_message_at=r.last_message_at,
        is_active=r.is_active,
        area=r.area,
        municipality=r.municipality,
        lat=r.lat,
        lon=r.lon,
        uncertainty_m=r.uncertainty_m,
        precision_tier=r.precision_tier,
        geocode_method=r.geocode_method,
        distance_m=round(r.distance_m),
        relation=r.relation,
        pushed=r.id in pushed,
    )


@router.get("/places/{place_id}/events", response_model=PlaceEvents)
async def place_events(
    place_id: uuid.UUID,
    device: CurrentDevice,
    session: Session,
    days: Annotated[int, Query(ge=1, le=90)] = 30,
) -> PlaceEvents:
    place = await _place(session, device.id, place_id)
    conn = await session.connection()
    since = await _since(conn, days)
    cats = list(place.categories)
    near = await events_near(conn, Circle(place.lat, place.lon, place.radius_m), cats, since)
    pushed = await _pushed(conn, place_id, [r.id for r in near])
    return PlaceEvents(
        place_id=place_id,
        days=days,
        events=[_summary(r, pushed) for r in near],
        municipality_only=await municipality_only_count(conn, place.kommunenummer, cats, since),
        district_notices=await _notices(conn, place.kommunenummer),
    )


# --- one event -----------------------------------------------------------------------------


class Message(BaseModel):
    seq: int
    created_at: datetime
    text: str


class ForPlace(BaseModel):
    place_id: uuid.UUID
    distance_m: int | None
    relation: Relation | None  # None: neither match nor imprecise nearby
    category_followed: bool
    pushed: bool


class EventDetail(BaseModel):
    id: str
    title: str
    category: str
    police_category: str
    severity: Literal["severe", "normal"]
    scope: Literal["kommune", "distrikt"]
    district: str | None
    municipality: str | None
    kommunenummer: str | None
    area: str | None
    is_active: bool | None
    is_control: bool
    first_message_at: datetime
    last_message_at: datetime
    lat: float | None
    lon: float | None
    uncertainty_m: int | None
    precision_tier: Literal["gate", "nabolag", "bydel"] | None
    geocode_method: str | None
    geocode_match: str | None
    messages: list[Message]
    for_place: ForPlace | None = None


@router.get("/events/{event_id}", response_model=EventDetail)
async def event_detail(
    event_id: str,
    device: CurrentDevice,
    session: Session,
    place_id: uuid.UUID | None = None,
) -> EventDetail:
    conn = await session.connection()
    e = (
        await conn.execute(
            text("""
                SELECT id, category, severity, scope, district, municipality, kommunenummer, area,
                       is_active, is_control, first_message_at, last_message_at,
                       ST_Y(geom::geometry) AS lat, ST_X(geom::geometry) AS lon, uncertainty_m,
                       precision_tier, geocode_method, geocode_match
                FROM events WHERE id = :id
            """),
            {"id": event_id},
        )
    ).one_or_none()
    if e is None:
        raise ApiError(404, "not_found", "No such event")
    messages = [
        Message(seq=m.seq, created_at=m.created_at, text=m.text)
        for m in await conn.execute(
            text("SELECT seq, created_at, text FROM event_messages WHERE event_id = :id ORDER BY seq"),
            {"id": event_id},
        )
    ]
    for_place = None
    if place_id is not None:
        place = await _place(session, device.id, place_id)
        followed = app_category(e.category) in place.categories
        distance = relation = None
        if e.lat is not None:
            row = (
                await conn.execute(
                    text("""
                        SELECT ST_Distance(e.geom, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography) AS d
                        FROM events e WHERE e.id = :id
                    """),
                    {"id": event_id, "lat": place.lat, "lon": place.lon},
                )
            ).one()
            distance = round(row.d)
            # The same rules as the place's list, over all time for this one event.
            near = await events_near(
                conn,
                Circle(place.lat, place.lon, place.radius_m),
                list(place.categories),
                e.first_message_at,  # just this event, however old
            )
            relation = next((r.relation for r in near if r.id == event_id), None)
        for_place = ForPlace(
            place_id=place_id,
            distance_m=distance,
            relation=relation,
            category_followed=followed,
            pushed=bool(await _pushed(conn, place_id, [event_id])),
        )
    return EventDetail(
        id=e.id,
        title=_title(e),
        category=app_category(e.category),
        police_category=e.category,
        severity=e.severity,
        scope=e.scope,
        district=district_name(e.district) if e.district else None,
        municipality=e.municipality,
        kommunenummer=e.kommunenummer,
        area=e.area,
        is_active=e.is_active,
        is_control=e.is_control,
        first_message_at=e.first_message_at,
        last_message_at=e.last_message_at,
        lat=e.lat,
        lon=e.lon,
        uncertainty_m=e.uncertainty_m,
        precision_tier=e.precision_tier,
        geocode_method=e.geocode_method,
        geocode_match=e.geocode_match,
        messages=messages,
        for_place=for_place,
    )


# --- feedback ------------------------------------------------------------------------------


class FeedbackIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    place_id: uuid.UUID


@router.post("/events/{event_id}/feedback", status_code=204)
async def feedback(event_id: str, body: FeedbackIn, device: CurrentDevice, session: Session) -> Response:
    """«Feil plassering?» (F10). One row per (event, place): a second tap changes nothing."""
    await _place(session, device.id, body.place_id)
    exists = (await session.execute(text("SELECT 1 FROM events WHERE id = :id"), {"id": event_id})).first()
    if exists is None:
        raise ApiError(404, "not_found", "No such event")
    await session.execute(
        text("""
            INSERT INTO placement_feedback (event_id, place_id)
            SELECT :e, :p
            WHERE NOT EXISTS (SELECT 1 FROM placement_feedback WHERE event_id = :e AND place_id = :p)
        """),
        {"e": event_id, "p": body.place_id},
    )
    return Response(status_code=204)
