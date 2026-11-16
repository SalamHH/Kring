"""M1 step 6: the §6.2 rules at their boundaries, the §8.5 query, D5 titles, and index use.

Events are placed at exact geodesic distances from a centre with ST_Project. Each case is checked
in both directions: events_near (circle → events, for lists and the preview) and places_for_event
(event → places, the §8.5 query for the notifier) must agree on what matches.
"""

from __future__ import annotations

import itertools
import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.match.categories import app_category
from app.match.rules import (
    IMPRECISE_NEARBY,
    MATCH,
    Circle,
    events_near,
    hidden_traffic_count,
    municipality_only_count,
    places_for_event,
)
from app.match.title import district_name, title

CENTER = (59.91483, 10.77318)  # Tøyen skole
LONG_AGO = datetime(2000, 1, 1, tzinfo=UTC)
_ids = itertools.count()


async def add_event(
    db: AsyncConnection,
    *,
    distance: float | None,
    tier: str | None = "gate",
    u: int | None = 100,
    category: str = "Brann",
    control: bool = False,
    scope: str = "kommune",
    severity: str = "severe",
    first: datetime | None = None,
    knr: str | None = "0301",
    bearing: float = 45.0,
) -> str:
    eid = f"t-{next(_ids)}"
    geom = (
        "ST_Project(ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography, CAST(:d AS float8), radians(:b))"
        if distance is not None
        else "NULL"
    )
    await db.execute(
        text(f"""
            INSERT INTO events (id, category, is_control, severity, first_message_at, last_message_at, raw,
                                geom, uncertainty_m, precision_tier, geocode_method, scope, kommunenummer,
                                district, municipality)
            VALUES (:id, :cat, :ctl, :sev, :first, :first, '{{}}', {geom}, :u, :tier, :method, :scope, :knr,
                    'Oslo Politidistrikt', 'Oslo')
        """),
        {
            "id": eid,
            "cat": category,
            "ctl": control,
            "sev": severity,
            "first": first or datetime.now(UTC),
            "lat": CENTER[0],
            "lon": CENTER[1],
            "d": distance,
            "b": bearing,
            "u": u if distance is not None else None,
            # Municipality-only events are tier bydel; district notices have no tier or method (step 2).
            "tier": tier if distance is not None else ("bydel" if scope == "kommune" else None),
            "method": "gate_tekst" if distance is not None else ("kommune" if scope == "kommune" else None),
            "scope": scope,
            "knr": knr if scope == "kommune" else None,
        },
    )
    return eid


async def distance_of(db: AsyncConnection, eid: str) -> float:
    return (
        await db.execute(
            text(
                "SELECT ST_Distance(geom, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography) "
                "FROM events WHERE id = :id"
            ),
            {"id": eid, "lat": CENTER[0], "lon": CENTER[1]},
        )
    ).scalar_one()


async def relation(
    db: AsyncConnection, eid: str, radius: float, categories: list[str] | None = None
) -> str | None:
    rows = await events_near(db, Circle(*CENTER, radius), categories or ["Brann"], LONG_AGO)
    return next((r.relation for r in rows if r.id == eid), None)


async def add_place(db: AsyncConnection, radius: int, categories: list[str] | None = None) -> uuid.UUID:
    device = uuid.uuid4()
    await db.execute(
        text("INSERT INTO devices (id, secret_hash) VALUES (:id, :h)"), {"id": device, "h": device.hex}
    )
    pid = uuid.uuid4()
    await db.execute(
        text("""
            INSERT INTO places (id, device_id, label, template, center, radius_m, categories, time_window)
            VALUES (:id, :d, 'Sted', 'annet', ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography, :r, :c,
                    CAST(:tw AS jsonb))
        """),
        {"id": pid, "d": device, "lat": CENTER[0], "lon": CENTER[1], "r": radius,
         "c": categories or ["Brann"], "tw": json.dumps({"all": True})},
    )  # fmt: skip
    return pid


async def matched_places(db: AsyncConnection, eid: str) -> set[uuid.UUID]:
    return {r.id for r in await places_for_event(db, eid)}


# --- the §6.2 table ------------------------------------------------------------------------

# (case, event, radius, expected relation)
CASES: list[tuple[str, dict[str, Any], int, str | None]] = [
    ("gate inside", {"distance": 500, "tier": "gate"}, 1000, MATCH),
    ("gate inside a small radius", {"distance": 250, "tier": "gate"}, 300, MATCH),
    ("gate outside", {"distance": 1200, "tier": "gate"}, 1000, None),
    ("nabolag inside, radius 1000", {"distance": 500, "tier": "nabolag", "u": 900}, 1000, MATCH),
    ("nabolag inside, radius 900", {"distance": 500, "tier": "nabolag", "u": 900}, 900, None),
    ("nabolag outside", {"distance": 1500, "tier": "nabolag", "u": 900}, 1000, None),
    ("bydel inside is only nearby", {"distance": 200, "tier": "bydel", "u": 2500}, 1000, IMPRECISE_NEARBY),
    ("bydel ring overlaps", {"distance": 3000, "tier": "bydel", "u": 2500}, 1000, IMPRECISE_NEARBY),
    ("bydel ring apart", {"distance": 4000, "tier": "bydel", "u": 2500}, 1000, None),
    (
        "planned control",
        {"distance": 100, "tier": "gate", "control": True, "category": "Trafikk"},
        1000,
        None,
    ),
    ("category not followed", {"distance": 100, "tier": "gate", "category": "Tyveri"}, 1000, None),
    ("municipality only", {"distance": None}, 2000, None),
    ("district notice", {"distance": None, "scope": "distrikt", "category": "Savnet"}, 2000, None),
]


@pytest.mark.parametrize(("case", "event", "radius", "expected"), CASES, ids=[c[0] for c in CASES])
async def test_rules_table(
    db: AsyncConnection, case: str, event: dict[str, Any], radius: int, expected: str | None
) -> None:
    eid = await add_event(db, **event)
    pid = await add_place(
        db, radius, ["Brann", "Savnet", "Trafikk"] if case != "category not followed" else None
    )
    assert (
        await relation(
            db, eid, radius, ["Brann", "Savnet", "Trafikk"] if case != "category not followed" else None
        )
        == expected
    )
    # §8.5 (event → places) agrees on matches, and never returns imprecise nearby.
    assert (pid in await matched_places(db, eid)) == (expected == MATCH)


async def test_radius_999_vs_1000_for_nabolag(db: AsyncConnection) -> None:
    eid = await add_event(db, distance=600, tier="nabolag", u=1000)
    assert await relation(db, eid, 999) is None
    assert await relation(db, eid, 1000) == MATCH
    gate = await add_event(db, distance=600, tier="gate")
    assert await relation(db, gate, 999) == MATCH  # gate counts at any radius


@pytest.mark.parametrize("tier", ["gate", "nabolag"])
async def test_distance_exactly_the_radius_matches(db: AsyncConnection, tier: str) -> None:
    eid = await add_event(db, distance=1500, tier=tier, u=800)
    d = await distance_of(db, eid)
    assert d == pytest.approx(1500, abs=1e-6)
    assert await relation(db, eid, d) == MATCH
    assert await relation(db, eid, d - 0.01) is None


async def test_distance_exactly_the_radius_plus_u_is_nearby(db: AsyncConnection) -> None:
    eid = await add_event(db, distance=3000, tier="bydel", u=2000)
    d = await distance_of(db, eid)
    assert await relation(db, eid, d - 2000) == IMPRECISE_NEARBY
    assert await relation(db, eid, d - 2000 - 0.01) is None


async def test_tier_boundaries_follow_the_stored_tier(db: AsyncConnection) -> None:
    # The tier is stored (§6.2: u ≤ 500 gate, ≤ 1 500 nabolag); the rules read the stored tier.
    at_500 = await add_event(db, distance=400, tier="gate", u=500)
    at_501 = await add_event(db, distance=400, tier="nabolag", u=501)
    at_1501 = await add_event(db, distance=400, tier="bydel", u=1501)
    assert await relation(db, at_500, 900) == MATCH
    assert await relation(db, at_501, 900) is None
    assert await relation(db, at_501, 1000) == MATCH
    assert await relation(db, at_1501, 2000) == IMPRECISE_NEARBY


async def test_andre_covers_its_police_categories_and_unlisted_ones(db: AsyncConnection) -> None:
    ulykke = await add_event(db, distance=100, category="Ulykke")
    ny = await add_event(db, distance=100, category="Narkotika")  # not in Appendix B
    brann = await add_event(db, distance=100, category="Brann")
    assert await relation(db, ulykke, 1000, ["Andre"]) == MATCH
    assert await relation(db, ny, 1000, ["Andre"]) == MATCH
    assert await relation(db, brann, 1000, ["Andre"]) is None
    assert await relation(db, ny, 1000, ["Brann"]) is None
    assert app_category("Narkotika") == "Andre"
    pid = await add_place(db, 1000, ["Andre"])
    assert pid in await matched_places(db, ny)


async def test_old_events_are_outside_the_window(db: AsyncConnection) -> None:
    old = await add_event(db, distance=100, first=datetime.now(UTC) - timedelta(days=31))
    rows = await events_near(db, Circle(*CENTER, 1000), ["Brann"], datetime.now(UTC) - timedelta(days=30))
    assert old not in {r.id for r in rows}


async def test_municipality_only_events_are_counted_not_listed(db: AsyncConnection) -> None:
    since = datetime.now(UTC) - timedelta(days=30)
    a = await add_event(db, distance=None, category="Brann")
    await add_event(db, distance=None, category="Brann", knr="3201")  # another municipality
    await add_event(db, distance=None, category="Tyveri")  # not followed
    await add_event(db, distance=None, category="Brann", first=datetime.now(UTC) - timedelta(days=40))
    await add_event(db, distance=None, scope="distrikt", category="Brann")
    assert a not in {r.id for r in await events_near(db, Circle(*CENTER, 2000), ["Brann"], LONG_AGO)}
    assert await municipality_only_count(db, "0301", ["Brann"], since) == 1
    assert await municipality_only_count(db, None, ["Brann"], since) == 0


async def test_hidden_traffic(db: AsyncConnection) -> None:
    since = LONG_AGO
    await add_event(db, distance=200, category="Trafikk")
    await add_event(db, distance=200, category="Trafikk", control=True)  # never counted
    await add_event(db, distance=200, category="Trafikk", tier="bydel", u=2000)  # nearby, not a match
    await add_event(db, distance=5000, category="Trafikk")
    c = Circle(*CENTER, 1000)
    assert await hidden_traffic_count(db, c, ["Brann"], since) == 1
    assert await hidden_traffic_count(db, c, ["Brann", "Trafikk"], since) == 0  # not hidden


async def test_places_for_event_respects_each_places_categories_and_radius(db: AsyncConnection) -> None:
    eid = await add_event(db, distance=800, tier="nabolag", u=900, category="Voldshendelse")
    big = await add_place(db, 1000, ["Vold"])
    small = await add_place(db, 900, ["Vold"])  # nabolag needs radius ≥ 1 000
    other = await add_place(db, 2000, ["Brann"])
    assert await matched_places(db, eid) == {big}
    assert small and other


# --- index use -----------------------------------------------------------------------------


async def test_queries_can_use_the_gist_indexes(db: AsyncConnection) -> None:
    """The queries can use the GiST indexes: with other access paths taken away, the planner uses
    them. If a query couldn't (e.g. a per-row radius in ST_DWithin's index condition), it would fall
    back to a sequential scan even so."""
    from app.match import rules

    await add_event(db, distance=100)
    await db.execute(text("SET LOCAL enable_seqscan = off"))
    # With sequential scans off the planner may still pick the time index instead, depending on
    # table statistics (flaky in the full suite). Drop it inside the test's transaction (rolled
    # back), so the only way to avoid a sequential scan is the GiST index.
    await db.execute(text("DROP INDEX events_first_idx"))
    params = {
        **rules.circle_params(Circle(*CENTER, 1000)),
        **rules.category_params(["Brann"]),
        "since": LONG_AGO,
    }
    plan = "\n".join(r[0] for r in await db.execute(text("EXPLAIN " + rules.NEAR_SQL), params))
    assert "events_geom_gix" in plan, plan
    plan = "\n".join(
        r[0]
        for r in await db.execute(
            text("EXPLAIN " + rules.PLACES_FOR_EVENT_SQL), {"id": "x", "app_category": "Brann"}
        )
    )
    assert "places_center_gix" in plan, plan


# --- titles (D5) ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "match", "area", "expected"),
    [
        ("adresse", "Trondheimsveien 33", "Grünerløkka", "Brann · Trondheimsveien 33"),
        ("kryss", "Mosseveien ved Ulvøya", "Nordstrand", "Brann · Mosseveien ved Ulvøya"),
        ("gate_area", "Hølandsgata", "Kampen", "Brann · Hølandsgata"),
        ("gate_tekst", "Skøyenveien", "Smestad", "Brann · Skøyenveien"),
        ("gate_omrade", "Jordstjerneveien", "Mortensrud", "Brann · Jordstjerneveien"),
        ("stedsnavn", "Torshov", "Torshov", "Brann · Torshov"),
        ("stedsnavn_utvidet", "Sandvika", "E18 Inn Sandvika", "Brann · Sandvika"),
        ("stedsnavn_tekst", "Gamlebyen", "", "Brann · Gamlebyen"),
        ("kommunenavn", "Lillestrøm", "", "Brann · Lillestrøm"),
        ("kommune", "", "Sentrum", "Brann · Sentrum"),  # municipality only: the area field
        ("kommune", "", "", "Brann · Oslo"),  # empty area: the municipality
        ("kommune", "", None, "Brann · Oslo"),
        (None, None, "Majorstua", "Brann · Majorstua"),  # never geocoded
        ("gate_tekst", "  ", "Kampen", "Brann · Kampen"),  # empty match falls through
    ],
)
def test_title_per_method(method: str | None, match: str | None, area: str | None, expected: str) -> None:
    assert (
        title(category="Brann", geocode_method=method, geocode_match=match, area=area, municipality="Oslo")
        == expected
    )


@pytest.mark.parametrize(
    ("category", "label"),
    [
        ("Voldshendelse", "Vold"),
        ("Ro og orden", "Ro og orden"),
        ("Ulykke", "Ulykke"),
        ("Narkotika", "Narkotika"),
    ],
)
def test_title_category(category: str, label: str) -> None:
    # App categories; for Andre, the police category (it says more than «Andre»).
    assert (
        title(category=category, geocode_method="gate_area", geocode_match="Hølandsgata")
        == f"{label} · Hølandsgata"
    )


def test_title_district_notice() -> None:
    t = title(
        category="Savnet",
        scope="distrikt",
        district="Oslo Politidistrikt",
        municipality="Oslo politidistrikt",
    )
    assert t == "Savnet · Oslo politidistrikt"
    assert district_name("Sør-Øst Politidistrikt") == "Sør-Øst politidistrikt"


def test_title_never_contains_police_text() -> None:
    # The title is built only from structured fields; there is no parameter for message text.
    import inspect

    assert "text" not in inspect.signature(title).parameters
