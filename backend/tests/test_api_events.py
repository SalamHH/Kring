"""M1 step 6: GET /v1/preview, GET /v1/places/{id}/events, GET /v1/events/{id} and
POST /v1/events/{id}/feedback (spec §8.6; D1, D2, D5)."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from tests.api_client import api_client
from tests.test_ingestor import N_OSLO, Env, env  # noqa: F401  (env is a fixture)
from tests.test_match_rules import CENTER, add_event

SKOLE = ["Vold", "Brann", "Savnet", "Ro og orden"]
SKOLE_POLICE = ["Voldshendelse", "Brann", "Savnet", "Ro og orden"]


async def register(client: httpx.AsyncClient) -> tuple[uuid.UUID, dict[str, str]]:
    r = await client.post("/v1/devices")
    assert r.status_code == 201
    return uuid.UUID(r.json()["device_id"]), {"Authorization": f"Bearer {r.json()['secret']}"}


async def add_place(
    db: AsyncConnection, device: uuid.UUID, radius: int = 1000, categories: list[str] | None = None,
    knr: str | None = "0301",
) -> uuid.UUID:  # fmt: skip
    pid = uuid.uuid4()
    await db.execute(
        text("""
            INSERT INTO places (id, device_id, label, template, center, radius_m, categories, time_window,
                                kommunenummer)
            VALUES (:id, :d, 'Skolen', 'skole', ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography, :r, :c,
                    CAST(:tw AS jsonb), :knr)
        """),
        {"id": pid, "d": device, "lat": CENTER[0], "lon": CENTER[1], "r": radius, "c": categories or SKOLE,
         "tw": json.dumps({"all": True}), "knr": knr},
    )  # fmt: skip
    return pid


# --- preview on the recorded Oslo quarter --------------------------------------------------


async def test_preview_equals_a_hand_count(env: Env) -> None:  # noqa: F811
    res = await env.cycle()
    assert res.ok and res.new == N_OSLO
    db = env.conn
    # The recorded quarter ends in the past; move it so its last message is now, so «the last 30
    # days» holds a month of it whenever the test runs.
    await db.execute(
        text("""
            UPDATE events SET first_message_at = first_message_at + d, last_message_at = last_message_at + d
            FROM (SELECT now() - max(last_message_at) AS d FROM events) s
        """)
    )
    hand = (
        await db.execute(
            text("""
                WITH c AS (
                  SELECT e.*, ST_Distance(e.geom, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography) AS d
                  FROM events e
                  WHERE e.scope = 'kommune' AND e.geom IS NOT NULL AND NOT e.is_control
                    AND e.first_message_at >= now() - interval '30 days'
                )
                SELECT
                  count(*) FILTER (WHERE category = ANY(:cats) AND d <= 1000
                                   AND precision_tier IN ('gate','nabolag')),
                  count(*) FILTER (WHERE category = ANY(:cats) AND d <= 1000
                                   AND precision_tier IN ('gate','nabolag') AND severity = 'severe'),
                  count(*) FILTER (WHERE category = 'Trafikk' AND d <= 1000
                                   AND precision_tier IN ('gate','nabolag')),
                  count(*) FILTER (WHERE category = ANY(:cats) AND precision_tier = 'bydel'
                                   AND d <= 1000 + uncertainty_m)
                FROM c
            """),
            {"lat": CENTER[0], "lon": CENTER[1], "cats": SKOLE_POLICE},
        )
    ).one()
    assert hand[0] > 0 and hand[3] > 0, f"the sample should have matches and nearby events: {hand}"
    async with api_client(db) as client:
        _, me = await register(client)
        r = await client.get(
            "/v1/preview",
            params={"lat": CENTER[0], "lon": CENTER[1], "radius_m": 1000, "categories": SKOLE},
            headers=me,
        )
        assert r.status_code == 200, r.text
        assert r.json() == {
            "days": 30,
            "matched": hand[0],
            "severe": hand[1],
            "hidden_traffic": hand[2],
            "imprecise_nearby": hand[3],
        }
        # Comma-separated categories give the same answer.
        r2 = await client.get(
            "/v1/preview",
            params={"lat": CENTER[0], "lon": CENTER[1], "radius_m": 1000, "categories": ",".join(SKOLE)},
            headers=me,
        )
        assert r2.json() == r.json()


@pytest.mark.parametrize(
    "params",
    [
        {"radius_m": 1050},
        {"radius_m": 200},
        {"categories": ["Narkotika"]},
        {"categories": [""]},
        {"categories": None},
        {"lat": 100},
        {"lat": None},
    ],
)
async def test_preview_validation(db: AsyncConnection, params: dict[str, Any]) -> None:
    base: dict[str, Any] = {"lat": CENTER[0], "lon": CENTER[1], "radius_m": 1000, "categories": ["Brann"]}
    query = {k: v for k, v in (base | params).items() if v is not None}
    async with api_client(db) as client:
        _, me = await register(client)
        r = await client.get("/v1/preview", params=query, headers=me)
        assert r.status_code == 422, r.text
        assert r.json()["error"] == "invalid_request"


async def test_preview_needs_a_device(db: AsyncConnection) -> None:
    async with api_client(db) as client:
        r = await client.get(
            "/v1/preview", params={"lat": 59.9, "lon": 10.7, "radius_m": 1000, "categories": "Brann"}
        )
        assert r.status_code == 401


# --- a place's events ----------------------------------------------------------------------


async def test_place_events(db: AsyncConnection) -> None:
    async with api_client(db) as client:
        device, me = await register(client)
        pid = await add_place(db, device)
        now = datetime.now(UTC)
        matched = await add_event(
            db, distance=300, tier="gate", category="Brann", first=now - timedelta(hours=2)
        )
        nearby = await add_event(db, distance=2500, tier="bydel", u=2000, category="Voldshendelse", first=now)
        await add_event(db, distance=300, tier="gate", category="Tyveri")  # not followed
        await add_event(
            db, distance=300, tier="gate", category="Brann", first=now - timedelta(days=40)
        )  # old
        await add_event(db, distance=None, category="Brann")  # municipality only: counted
        await add_event(db, distance=None, category="Savnet", knr="3201")  # another municipality
        notice = await add_event(db, distance=None, scope="distrikt", category="Savnet")
        await add_event(
            db, distance=None, scope="distrikt", category="Trafikk", first=now - timedelta(days=2)
        )
        await db.execute(
            text("INSERT INTO notifications (place_id, event_id, kind) VALUES (:p, :e, 'push')"),
            {"p": pid, "e": matched},
        )

        r = await client.get(f"/v1/places/{pid}/events", headers=me)
        assert r.status_code == 200, r.text
        body = r.json()
        assert [e["id"] for e in body["events"]] == [nearby, matched]  # newest first
        m = body["events"][1]
        assert m["relation"] == "match" and m["pushed"] is True and m["distance_m"] == 300
        assert m["title"] == "Brann · Oslo" and m["category"] == "Brann" and m["precision_tier"] == "gate"
        n = body["events"][0]
        assert n["relation"] == "imprecise_nearby" and n["pushed"] is False and n["category"] == "Vold"
        assert body["municipality_only"] == 1
        assert [x["id"] for x in body["district_notices"]] == [notice]  # the 2-day-old one is gone
        assert body["district_notices"][0]["title"] == "Savnet · Oslo politidistrikt"
        assert body["district_notices"][0]["district"] == "Oslo politidistrikt"

        r = await client.get(f"/v1/places/{pid}/events", params={"days": 60}, headers=me)
        assert len(r.json()["events"]) == 3
        assert (
            await client.get(f"/v1/places/{pid}/events", params={"days": 0}, headers=me)
        ).status_code == 422
        assert (
            await client.get(f"/v1/places/{pid}/events", params={"days": 91}, headers=me)
        ).status_code == 422


async def test_district_notices_follow_the_districts_of_the_places_municipality(db: AsyncConnection) -> None:
    async with api_client(db) as client:
        device, me = await register(client)
        # The municipality has a stored event in Oslo politidistrikt, so that district is the place's.
        await add_event(db, distance=5000, category="Brann")
        await add_event(db, distance=None, scope="distrikt", category="Savnet")
        outside = await add_place(db, device, knr="5001")  # no stored events in its municipality
        r = await client.get(f"/v1/places/{outside}/events", headers=me)
        assert r.json()["district_notices"] == [] and r.json()["municipality_only"] == 0


async def test_another_devices_place_is_404(db: AsyncConnection) -> None:
    async with api_client(db) as client:
        owner, _ = await register(client)
        _, other = await register(client)
        pid = await add_place(db, owner)
        r = await client.get(f"/v1/places/{pid}/events", headers=other)
        assert r.status_code == 404


# --- one event -----------------------------------------------------------------------------


async def add_messages(db: AsyncConnection, eid: str, texts: list[str]) -> None:
    base = datetime.now(UTC) - timedelta(hours=1)
    for i, t in reversed(list(enumerate(texts))):
        await db.execute(
            text("INSERT INTO event_messages (event_id, seq, created_at, text) VALUES (:e, :s, :c, :t)"),
            {"e": eid, "s": i, "c": base + timedelta(minutes=10 * i), "t": t},
        )


async def test_event_detail(db: AsyncConnection) -> None:
    async with api_client(db) as client:
        device, me = await register(client)
        pid = await add_place(db, device)
        eid = await add_event(db, distance=400, tier="nabolag", u=900, category="Voldshendelse")
        await db.execute(
            text(
                "UPDATE events SET geocode_match = 'Hølandsgata', area = 'Kampen', is_active = true "
                "WHERE id = :e"
            ),
            {"e": eid},
        )
        await add_messages(db, eid, ["Melding om slagsmål.", "Politiet er på stedet.", "Avsluttet."])

        r = await client.get(f"/v1/events/{eid}", headers=me)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["title"] == "Vold · Hølandsgata"
        assert d["category"] == "Vold" and d["police_category"] == "Voldshendelse"
        assert [m["text"] for m in d["messages"]] == [
            "Melding om slagsmål.",
            "Politiet er på stedet.",
            "Avsluttet.",
        ]
        assert (
            d["precision_tier"] == "nabolag"
            and d["uncertainty_m"] == 900
            and d["geocode_method"] == "gate_tekst"
        )
        assert d["lat"] and d["lon"] and d["for_place"] is None
        assert d["district"] == "Oslo politidistrikt"

        r = await client.get(f"/v1/events/{eid}", params={"place_id": str(pid)}, headers=me)
        fp = r.json()["for_place"]
        assert fp == {"place_id": str(pid), "distance_m": 400, "relation": "match", "category_followed": True,
                      "pushed": False}  # fmt: skip

        # Radius 900: nabolag doesn't count, so it's neither match nor nearby, but the distance is shown.
        await db.execute(text("UPDATE places SET radius_m = 900 WHERE id = :p"), {"p": pid})
        fp = (await client.get(f"/v1/events/{eid}", params={"place_id": str(pid)}, headers=me)).json()[
            "for_place"
        ]
        assert fp["relation"] is None and fp["distance_m"] == 400

        _, other = await register(client)
        assert (
            await client.get(f"/v1/events/{eid}", params={"place_id": str(pid)}, headers=other)
        ).status_code == 404
        assert (await client.get(f"/v1/events/{eid}", headers=other)).status_code == 200  # events are public
        assert (await client.get("/v1/events/nope", headers=me)).status_code == 404


async def test_district_notice_detail_has_no_point(db: AsyncConnection) -> None:
    async with api_client(db) as client:
        device, me = await register(client)
        pid = await add_place(db, device)
        nid = await add_event(db, distance=None, scope="distrikt", category="Savnet")
        d = (await client.get(f"/v1/events/{nid}", params={"place_id": str(pid)}, headers=me)).json()
        assert d["scope"] == "distrikt" and d["lat"] is None and d["precision_tier"] is None
        assert d["title"] == "Savnet · Oslo politidistrikt"
        assert d["for_place"]["relation"] is None and d["for_place"]["distance_m"] is None


# --- feedback ------------------------------------------------------------------------------


async def test_feedback(db: AsyncConnection) -> None:
    async with api_client(db) as client:
        device, me = await register(client)
        pid = await add_place(db, device)
        eid = await add_event(db, distance=100)
        for _ in range(2):
            r = await client.post(f"/v1/events/{eid}/feedback", json={"place_id": str(pid)}, headers=me)
            assert r.status_code == 204
        n = (
            await db.execute(text("SELECT count(*) FROM placement_feedback WHERE event_id = :e"), {"e": eid})
        ).scalar()
        assert n == 1  # a second tap changes nothing

        r = await client.post("/v1/events/nope/feedback", json={"place_id": str(pid)}, headers=me)
        assert r.status_code == 404
        _, other = await register(client)
        r = await client.post(f"/v1/events/{eid}/feedback", json={"place_id": str(pid)}, headers=other)
        assert r.status_code == 404
        r = await client.post(f"/v1/events/{eid}/feedback", json={}, headers=me)
        assert r.status_code == 422
