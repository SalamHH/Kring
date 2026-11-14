"""Places (§8.6 `GET/POST /v1/places`, `PATCH/DELETE /v1/places/{id}`; F1-F3, D9, D10).

Validation follows §8.4 and §6:
- label: 1-40 characters after trimming;
- radius 300-2 000 m in steps of 100 (default 1 000);
- template one of §6.1;
- categories: app categories (Appendix B), at least one;
- time_window: {"all": true}, or {"days": [ISO weekdays 1-7], "from": "HH:MM", "to": "HH:MM"} with
  from before to (decided 2026-11-14: no windows across midnight in M1).

Templates fill in categories and time window on the server when they are left out (§6.1), so the
app and the server can't drift. The municipality comes from Kartverket's reverse point lookup.
A place outside the ingested fylker is allowed and flagged `covered: false` (D9).
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentDevice, Session
from app.api.errors import ApiError
from app.geocode.cache import GeocodeCache
from app.geocode.kartverket import LookupFailed
from app.geocode.search import kommune_for_punkt
from app.match.categories import APP_CATEGORIES, canonical

router = APIRouter(prefix="/v1/places", tags=["places"])

Template = Literal["skole", "hjem", "hytte", "jobb", "annet"]
Label = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=40)]

ALL_DAY: dict[str, Any] = {"all": True}
WEEKDAYS = [1, 2, 3, 4, 5]

# §6.1. «Annet» is all categories except Trafikk, as the table says, so it includes Andre
# (decided 2026-11-14; Appendix B's «off by default» applies to the other templates).
TEMPLATES: dict[str, tuple[list[str], dict[str, Any]]] = {
    "skole": (["Vold", "Brann", "Savnet", "Ro og orden"], {"days": WEEKDAYS, "from": "08:00", "to": "16:00"}),
    "hjem": (["Innbrudd", "Brann", "Vold", "Ro og orden"], ALL_DAY),
    "hytte": (["Innbrudd", "Brann"], ALL_DAY),
    "jobb": (["Vold", "Brann"], {"days": WEEKDAYS, "from": "07:00", "to": "17:00"}),
    "annet": ([c for c in APP_CATEGORIES if c != "Trafikk"], ALL_DAY),
}

_HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


class AllDay(BaseModel):
    model_config = ConfigDict(extra="forbid")
    all: Literal[True]


class Window(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    days: list[int] = Field(min_length=1, max_length=7)
    from_: str = Field(alias="from")
    to: str

    @field_validator("days")
    @classmethod
    def _days(cls, v: list[int]) -> list[int]:
        if any(d < 1 or d > 7 for d in v):
            raise ValueError("days are ISO weekdays, 1 (Monday) to 7 (Sunday)")
        return sorted(set(v))

    @field_validator("from_", "to")
    @classmethod
    def _hhmm(cls, v: str) -> str:
        if not _HHMM.match(v):
            raise ValueError("time must be HH:MM, 00:00 to 23:59")
        return v

    @model_validator(mode="after")
    def _order(self) -> Window:
        if self.from_ >= self.to:
            raise ValueError("from must be before to")
        return self


TimeWindow = AllDay | Window


def window_json(w: TimeWindow) -> dict[str, Any]:
    if isinstance(w, AllDay):
        return dict(ALL_DAY)
    return {"days": w.days, "from": w.from_, "to": w.to}


def _radius(v: int) -> int:
    if not 300 <= v <= 2000 or v % 100:
        raise ValueError("radius_m must be 300-2000 in steps of 100")
    return v


def _categories(v: list[str] | None) -> list[str] | None:
    if v is None:
        return v
    v = canonical(v)
    if not v:
        raise ValueError("at least one category")
    return v


class PlaceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: Label
    template: Template
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    radius_m: int = 1000
    categories: list[str] | None = None  # None: the template's
    time_window: TimeWindow | None = None  # None: the template's
    push: bool = True

    _r = field_validator("radius_m")(_radius)
    _c = field_validator("categories")(_categories)


class PlaceUpdate(BaseModel):
    """Only the fields sent are changed. A new template doesn't change categories or window."""

    model_config = ConfigDict(extra="forbid")
    label: Label | None = None
    template: Template | None = None
    lat: float | None = Field(default=None, ge=-90, le=90)
    lon: float | None = Field(default=None, ge=-180, le=180)
    radius_m: int | None = None
    categories: list[str] | None = None
    time_window: TimeWindow | None = None
    push: bool | None = None

    _r = field_validator("radius_m")(lambda v: v if v is None else _radius(v))
    _c = field_validator("categories")(_categories)

    @model_validator(mode="after")
    def _no_nulls_and_both_coordinates(self) -> PlaceUpdate:
        for name in self.model_fields_set:
            if getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        if ("lat" in self.model_fields_set) != ("lon" in self.model_fields_set):
            raise ValueError("lat and lon are changed together")
        return self


class PlaceOut(BaseModel):
    id: uuid.UUID
    label: str
    template: Template
    lat: float
    lon: float
    radius_m: int
    categories: list[str]
    time_window: dict[str, Any]
    push: bool
    kommunenummer: str | None
    covered: bool  # inside the ingested fylker (D9): incidents exist only there
    created_at: datetime


_SELECT = """
    SELECT id, label, template, ST_Y(center::geometry) AS lat, ST_X(center::geometry) AS lon,
           radius_m, categories, time_window, push, kommunenummer, created_at
    FROM places
"""


def _out(request: Request, row: Any) -> PlaceOut:
    tw = row.time_window if isinstance(row.time_window, dict) else json.loads(row.time_window)
    return PlaceOut(
        id=row.id,
        label=row.label,
        template=row.template,
        lat=row.lat,
        lon=row.lon,
        radius_m=row.radius_m,
        categories=list(row.categories),
        time_window=tw,
        push=row.push,
        kommunenummer=row.kommunenummer,
        covered=request.app.state.settings.kommune_allowed(row.kommunenummer),
        created_at=row.created_at,
    )


async def _kommune(request: Request, session: AsyncSession, lat: float, lon: float) -> str | None:
    cache = GeocodeCache(await session.connection())
    try:
        return await kommune_for_punkt(request.app.state.kartverket, cache, lat, lon)
    except LookupFailed as e:
        raise ApiError(502, "kartverket_unavailable", "Kartverket did not answer; try again") from e


async def _get(
    request: Request, session: AsyncSession, device_id: uuid.UUID, place_id: uuid.UUID
) -> PlaceOut:
    row = (
        await session.execute(
            text(_SELECT + " WHERE id = :id AND device_id = :d"), {"id": place_id, "d": device_id}
        )
    ).one_or_none()
    if row is None:
        raise ApiError(404, "not_found", "No such place")
    return _out(request, row)


@router.get("", response_model=list[PlaceOut])
async def list_places(request: Request, device: CurrentDevice, session: Session) -> list[PlaceOut]:
    rows = await session.execute(
        text(_SELECT + " WHERE device_id = :d ORDER BY created_at, id"), {"d": device.id}
    )
    return [_out(request, r) for r in rows]


@router.post("", status_code=201, response_model=PlaceOut)
async def create_place(
    request: Request, body: PlaceCreate, device: CurrentDevice, session: Session
) -> PlaceOut:
    # Lock the device row so two concurrent creates can't both pass the limit (D10).
    await session.execute(text("SELECT 1 FROM devices WHERE id = :d FOR UPDATE"), {"d": device.id})
    n = (
        await session.execute(text("SELECT count(*) FROM places WHERE device_id = :d"), {"d": device.id})
    ).scalar()
    limit = request.app.state.settings.places_per_device
    if n >= limit:
        raise ApiError(409, "place_limit", f"A device can have at most {limit} places")
    default_categories, default_window = TEMPLATES[body.template]
    categories = body.categories or canonical(default_categories)
    window = window_json(body.time_window) if body.time_window else default_window
    knr = await _kommune(request, session, body.lat, body.lon)
    place_id = uuid.uuid4()
    await session.execute(
        text("""
            INSERT INTO places (id, device_id, label, template, center, radius_m, categories, time_window,
                                push, kommunenummer)
            VALUES (:id, :d, :label, :template, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography,
                    :radius, :categories, CAST(:tw AS jsonb), :push, :knr)
        """),
        {
            "id": place_id,
            "d": device.id,
            "label": body.label,
            "template": body.template,
            "lon": body.lon,
            "lat": body.lat,
            "radius": body.radius_m,
            "categories": categories,
            "tw": json.dumps(window),
            "push": body.push,
            "knr": knr,
        },
    )
    return await _get(request, session, device.id, place_id)


@router.patch("/{place_id}", response_model=PlaceOut)
async def update_place(
    request: Request, place_id: uuid.UUID, body: PlaceUpdate, device: CurrentDevice, session: Session
) -> PlaceOut:
    await _get(request, session, device.id, place_id)  # 404 for another device's place
    sets: list[str] = []
    params: dict[str, Any] = {"id": place_id}
    fields = body.model_fields_set
    for name, col in (
        ("label", "label"),
        ("template", "template"),
        ("radius_m", "radius_m"),
        ("push", "push"),
    ):
        if name in fields:
            sets.append(f"{col} = :{name}")
            params[name] = getattr(body, name)
    if "categories" in fields:
        sets.append("categories = :categories")
        params["categories"] = body.categories
    if "time_window" in fields and body.time_window is not None:
        sets.append("time_window = CAST(:tw AS jsonb)")
        params["tw"] = json.dumps(window_json(body.time_window))
    if "lat" in fields and body.lat is not None and body.lon is not None:
        sets.append("center = ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography, kommunenummer = :knr")
        params.update(lat=body.lat, lon=body.lon, knr=await _kommune(request, session, body.lat, body.lon))
    if sets:
        await session.execute(text(f"UPDATE places SET {', '.join(sets)} WHERE id = :id"), params)
    return await _get(request, session, device.id, place_id)


@router.delete("/{place_id}", status_code=204)
async def delete_place(place_id: uuid.UUID, device: CurrentDevice, session: Session) -> Response:
    # Its notifications go by ON DELETE CASCADE; placement_feedback has no foreign key (as in
    # DELETE /v1/devices/me), so its rows are deleted by hand.
    deleted = (
        await session.execute(
            text("DELETE FROM places WHERE id = :id AND device_id = :d RETURNING id"),
            {"id": place_id, "d": device.id},
        )
    ).first()
    if deleted is None:
        raise ApiError(404, "not_found", "No such place")
    await session.execute(text("DELETE FROM placement_feedback WHERE place_id = :id"), {"id": place_id})
    return Response(status_code=204)
