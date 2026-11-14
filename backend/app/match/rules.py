"""The §6.2 event rules as queries (spec §6.2, §8.5; D1).

For a circle (a place, or the preview's centre and radius) and a set of app categories, an event
is one of:
- **match**: in the categories, not a planned control, a point within the radius, and tier gate,
  or tier nabolag when the radius is at least 1 000 m;
- **imprecise nearby**: in the categories, not a control, tier bydel with a point, and its
  uncertainty circle overlaps the circle (distance ≤ radius + u). Never pushed (D1);
- otherwise nothing. That includes tier nabolag inside a radius under 1 000 m, and
  municipality-only events (no point), which are only counted (`municipality_only_count`).

Only events with `scope = 'kommune'` are considered: district-wide notices (step 2) have no point,
and are filtered by scope explicitly rather than by relying on a NULL geom.

`events_near` finds candidates with ST_DWithin on events.geom, so the GiST index is used, widening
the radius by the largest stored uncertainty for imprecise nearby. `places_for_event` is the §8.5
query in the other direction, for the notifier (step 7).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.match.categories import POLICE_CATEGORIES, app_category, police_categories

MATCH = "match"
IMPRECISE_NEARBY = "imprecise_nearby"

LISTED_POLICE = [p for ps in POLICE_CATEGORIES.values() for p in ps]


def category_params(app_categories: list[str]) -> dict[str, Any]:
    """Bind parameters for CATEGORY_SQL. Andre also covers police categories Appendix B doesn't
    list (app_category)."""
    return {
        "police": police_categories(app_categories),
        "andre": "Andre" in app_categories,
        "listed": LISTED_POLICE,
    }


CATEGORY_SQL = "(e.category = ANY(:police) OR (:andre AND e.category <> ALL(:listed)))"

CIRCLE_SQL = "ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography"

# The relation of one event to the circle; NULL when it is neither.
DISTANCE_SQL = f"ST_Distance(e.geom, {CIRCLE_SQL})"

# The relation of one event to the circle; NULL when it is neither. Distances are compared with
# ST_Distance, the distance the API reports: ST_DWithin is false at exactly the radius (it differs
# from ST_Distance by under a micrometre), and §6.2 says «≤ radius» (decided 2026-11-14).
RELATION_SQL = f"""
    CASE
      WHEN {DISTANCE_SQL} <= :radius
           AND (e.precision_tier = 'gate' OR (e.precision_tier = 'nabolag' AND :radius >= 1000))
        THEN '{MATCH}'
      WHEN e.precision_tier = 'bydel' AND {DISTANCE_SQL} <= :radius + e.uncertainty_m
        THEN '{IMPRECISE_NEARBY}'
    END
"""

# ST_DWithin only narrows the candidates through the GiST index; the margin covers its strictness.
INDEX_MARGIN_M = 1

NEAR_SQL = f"""
    SELECT * FROM (
      SELECT e.id, e.category, e.severity, e.first_message_at, e.last_message_at, e.is_active,
             e.area, e.municipality, e.district, e.kommunenummer, e.scope,
             e.precision_tier, e.uncertainty_m, e.geocode_method, e.geocode_match,
             ST_Y(e.geom::geometry) AS lat, ST_X(e.geom::geometry) AS lon,
             {DISTANCE_SQL} AS distance_m,
             {RELATION_SQL} AS relation
      FROM events e
      WHERE e.scope = 'kommune'
        AND e.geom IS NOT NULL
        AND NOT e.is_control
        AND e.first_message_at >= :since
        AND {CATEGORY_SQL}
        AND ST_DWithin(e.geom, {CIRCLE_SQL},
                       :radius + COALESCE((SELECT max(uncertainty_m) FROM events), 0) + {INDEX_MARGIN_M})
    ) c
    WHERE relation IS NOT NULL
    ORDER BY first_message_at DESC, id
"""


MAX_PLACE_RADIUS_M = 2000  # places.radius_m CHECK

# §8.5, with two changes (decided 2026-11-14): the place's own radius varies per row, so the
# index condition uses the largest radius allowed and the radius is checked after; and the
# distance is compared with ST_Distance, as in RELATION_SQL.
PLACES_FOR_EVENT_SQL = f"""
    SELECT p.id, p.device_id, p.label, p.radius_m, p.time_window, p.push, p.created_at,
           ST_Distance(p.center, e.geom) AS distance_m
    FROM events e
    JOIN places p ON ST_DWithin(p.center, e.geom, {MAX_PLACE_RADIUS_M + INDEX_MARGIN_M})
    WHERE e.id = :id
      AND :app_category = ANY (p.categories)
      AND ST_Distance(p.center, e.geom) <= p.radius_m
      AND (e.precision_tier = 'gate' OR (e.precision_tier = 'nabolag' AND p.radius_m >= 1000))
    ORDER BY p.created_at, p.id
"""


@dataclass(frozen=True)
class Circle:
    lat: float
    lon: float
    radius_m: float


def circle_params(c: Circle) -> dict[str, Any]:
    return {"lat": c.lat, "lon": c.lon, "radius": c.radius_m}


async def events_near(
    conn: AsyncConnection, circle: Circle, app_categories: list[str], since: datetime
) -> list[Any]:
    """Matched and imprecise-nearby events since `since`, newest first, with distance_m and
    relation."""
    rows = await conn.execute(
        text(NEAR_SQL), {**circle_params(circle), **category_params(app_categories), "since": since}
    )
    return list(rows)


async def hidden_traffic_count(
    conn: AsyncConnection, circle: Circle, app_categories: list[str], since: datetime
) -> int:
    """Trafikk events that would match if the circle followed Trafikk: what F3 says is hidden.
    0 when Trafikk is already followed."""
    if "Trafikk" in app_categories:
        return 0
    return sum(1 for r in await events_near(conn, circle, ["Trafikk"], since) if r.relation == MATCH)


async def municipality_only_count(
    conn: AsyncConnection, kommunenummer: str | None, app_categories: list[str], since: datetime
) -> int:
    """Events in the categories with no point, in the municipality (D1: counted, never listed)."""
    if not kommunenummer:
        return 0
    sql = f"""
        SELECT count(*) FROM events e
        WHERE e.scope = 'kommune' AND e.geom IS NULL AND NOT e.is_control
          AND e.kommunenummer = :knr AND e.first_message_at >= :since AND {CATEGORY_SQL}
    """
    params = {"knr": kommunenummer, "since": since, **category_params(app_categories)}
    return int((await conn.execute(text(sql), params)).scalar_one())


async def places_for_event(conn: AsyncConnection, event_id: str) -> list[Any]:
    """The §8.5 match query: the places an event matches (not imprecise nearby). For the notifier
    (step 7). Uses the GiST index on places.center."""
    ev = (
        await conn.execute(
            text("""
                SELECT category, is_control, scope, precision_tier, geom IS NOT NULL AS has_point
                FROM events WHERE id = :id
            """),
            {"id": event_id},
        )
    ).one_or_none()
    if ev is None or ev.scope != "kommune" or not ev.has_point or ev.is_control:
        return []
    if ev.precision_tier not in ("gate", "nabolag"):
        return []
    rows = await conn.execute(
        text(PLACES_FOR_EVENT_SQL), {"id": event_id, "app_category": app_category(ev.category)}
    )
    return list(rows)
