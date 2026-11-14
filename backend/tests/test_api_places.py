"""M1 step 5: places CRUD and geocode search (spec §6, §8.4, §8.6; D9, D10).

Kartverket is replayed from tests/fixtures/kartverket/api/search.json (scripts/record_search.py).
A request that isn't recorded fails the test.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from app.api.deps import get_session, session_scope
from app.api.main import create_app
from app.geocode.kartverket import KartverketClient
from app.geocode.text import norm
from app.settings import Settings

RECORDED = json.loads((Path(__file__).parent / "fixtures" / "kartverket" / "api" / "search.json").read_text())

TOYEN_SKOLE = {"lat": 59.91483, "lon": 10.77318}
HOLANDSGATA_1A = {"lat": 59.9089, "lon": 10.77923}
TRONDHEIM = {"lat": 63.43049, "lon": 10.39506}
NORDSJOEN = {"lat": 58.5, "lon": 3.0}


def _key(path: str, params: dict[str, Any]) -> tuple[str, tuple[tuple[str, str], ...]]:
    return path, tuple(sorted((k, str(v)) for k, v in params.items()))


class Kartverket:
    """Replays the recordings; `fail` makes every call answer 503; `calls` counts requests."""

    def __init__(self) -> None:
        self.answers = {_key(r["path"], r["params"]): r for r in RECORDED}
        self.fail = False
        self.calls = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls += 1
        if self.fail:
            return httpx.Response(503, text="unavailable")
        rec = self.answers.get(_key(request.url.path, dict(request.url.params)))
        if rec is None:
            raise AssertionError(f"not recorded: {request.url}")
        if isinstance(rec["body"], str):
            return httpx.Response(rec["status"], text=rec["body"])
        return httpx.Response(rec["status"], json=rec["body"])


class Env:
    def __init__(self, client: httpx.AsyncClient, db: AsyncConnection, kv: Kartverket) -> None:
        self.client = client
        self.db = db
        self.kv = kv

    async def device(self) -> dict[str, str]:
        r = await self.client.post("/v1/devices")
        assert r.status_code == 201
        return {"Authorization": f"Bearer {r.json()['secret']}"}

    async def scalar(self, sql: str, **params: Any) -> Any:
        return (await self.db.execute(text(sql), params)).scalar()


@pytest.fixture
async def env(db: AsyncConnection) -> AsyncIterator[Env]:
    settings = Settings(rate_limit_per_minute=1000, register_limit_per_hour=1000, search_limit_per_minute=5)
    app = create_app(settings)

    async def test_session() -> AsyncIterator[AsyncSession]:
        async with session_scope(AsyncSession(bind=db, join_transaction_mode="create_savepoint")) as s:
            yield s

    app.dependency_overrides[get_session] = test_session
    kv = Kartverket()
    async with respx.mock(assert_all_called=False) as router, httpx.AsyncClient() as http:
        router.route(host="ws.geonorge.no").mock(side_effect=kv)
        app.state.kartverket = KartverketClient(
            http,
            settings.adresse_url,
            settings.stedsnavn_urls[:1],
            retry_delays_s=(),
            min_spacing_s=0,
            kommune_punkt_url=settings.kommune_punkt_url,
        )
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            yield Env(client, db, kv)


def place(**kw: Any) -> dict[str, Any]:
    return {"label": "Skolen", "template": "skole", **TOYEN_SKOLE, **kw}


# --- CRUD ----------------------------------------------------------------------------------


async def test_crud_round_trip(env: Env) -> None:
    me = await env.device()
    r = await env.client.post("/v1/places", headers=me, json=place(label="  Tøyen skole  "))
    assert r.status_code == 201, r.text
    created = r.json()
    assert created["label"] == "Tøyen skole"  # trimmed
    assert (created["lat"], created["lon"]) == (TOYEN_SKOLE["lat"], TOYEN_SKOLE["lon"])
    assert created["radius_m"] == 1000 and created["push"] is True
    assert created["kommunenummer"] == "0301" and created["covered"] is True

    r = await env.client.get("/v1/places", headers=me)
    assert r.status_code == 200 and r.json() == [created]

    r = await env.client.patch(
        f"/v1/places/{created['id']}",
        headers=me,
        json={
            "label": "Skole",
            "radius_m": 700,
            "categories": ["Brann", "Vold"],
            "time_window": {"all": True},
            "push": False,
        },
    )
    assert r.status_code == 200, r.text
    updated = r.json()
    assert updated["label"] == "Skole" and updated["radius_m"] == 700 and updated["push"] is False
    assert updated["categories"] == ["Vold", "Brann"]  # app order, as in Appendix B
    assert updated["time_window"] == {"all": True}
    assert updated["template"] == "skole" and updated["kommunenummer"] == "0301"

    r = await env.client.patch(f"/v1/places/{created['id']}", headers=me, json=HOLANDSGATA_1A)
    assert r.status_code == 200
    assert (r.json()["lat"], r.json()["lon"]) == (HOLANDSGATA_1A["lat"], HOLANDSGATA_1A["lon"])

    r = await env.client.delete(f"/v1/places/{created['id']}", headers=me)
    assert r.status_code == 204
    assert (await env.client.get("/v1/places", headers=me)).json() == []
    assert await env.scalar("SELECT count(*) FROM places") == 0


async def test_skole_without_categories_gets_template_defaults(env: Env) -> None:
    me = await env.device()
    r = await env.client.post("/v1/places", headers=me, json=place())
    assert r.status_code == 201
    assert r.json()["categories"] == ["Vold", "Brann", "Savnet", "Ro og orden"]
    assert r.json()["time_window"] == {"days": [1, 2, 3, 4, 5], "from": "08:00", "to": "16:00"}


@pytest.mark.parametrize(
    ("template", "categories", "window"),
    [
        ("hjem", ["Vold", "Brann", "Ro og orden", "Innbrudd"], {"all": True}),
        ("hytte", ["Brann", "Innbrudd"], {"all": True}),
        ("jobb", ["Vold", "Brann"], {"days": [1, 2, 3, 4, 5], "from": "07:00", "to": "17:00"}),
        ("annet", ["Vold", "Brann", "Savnet", "Ro og orden", "Innbrudd", "Tyveri", "Andre"], {"all": True}),
    ],
)
async def test_other_template_defaults(env: Env, template: str, categories: list[str], window: Any) -> None:
    me = await env.device()
    r = await env.client.post("/v1/places", headers=me, json=place(template=template))
    assert r.status_code == 201
    assert r.json()["categories"] == categories and r.json()["time_window"] == window


async def test_explicit_categories_and_window_win_over_the_template(env: Env) -> None:
    me = await env.device()
    window = {"days": [6, 7, 6], "from": "10:00", "to": "12:30"}
    r = await env.client.post(
        "/v1/places", headers=me, json=place(categories=["Trafikk", "Brann", "Brann"], time_window=window)
    )
    assert r.status_code == 201
    assert r.json()["categories"] == ["Brann", "Trafikk"]
    assert r.json()["time_window"] == {"days": [6, 7], "from": "10:00", "to": "12:30"}


async def test_another_devices_place_is_404(env: Env) -> None:
    owner, other = await env.device(), await env.device()
    pid = (await env.client.post("/v1/places", headers=owner, json=place())).json()["id"]
    assert (await env.client.get("/v1/places", headers=other)).json() == []
    r = await env.client.patch(f"/v1/places/{pid}", headers=other, json={"label": "Mine"})
    assert r.status_code == 404 and r.json()["error"] == "not_found"
    assert (await env.client.delete(f"/v1/places/{pid}", headers=other)).status_code == 404
    assert await env.scalar("SELECT label FROM places WHERE id = :id", id=pid) == "Skolen"
    unknown = "00000000-0000-0000-0000-000000000000"
    assert (await env.client.delete(f"/v1/places/{unknown}", headers=owner)).status_code == 404


INVALID_CREATE: list[tuple[str, dict[str, Any]]] = [
    ("empty label", {"label": "   "}),
    ("label too long", {"label": "x" * 41}),
    ("radius too small", {"radius_m": 200}),
    ("radius too large", {"radius_m": 2100}),
    ("radius not a step of 100", {"radius_m": 1050}),
    ("unknown template", {"template": "barnehage"}),
    ("unknown category", {"categories": ["Brann", "Narkotika"]}),
    ("police category", {"categories": ["Voldshendelse"]}),
    ("no categories", {"categories": []}),
    ("weekday 0", {"time_window": {"days": [0], "from": "08:00", "to": "16:00"}}),
    ("weekday 8", {"time_window": {"days": [8], "from": "08:00", "to": "16:00"}}),
    ("no days", {"time_window": {"days": [], "from": "08:00", "to": "16:00"}}),
    ("bad time", {"time_window": {"days": [1], "from": "8:00", "to": "16:00"}}),
    ("24:00", {"time_window": {"days": [1], "from": "08:00", "to": "24:00"}}),
    ("from after to", {"time_window": {"days": [1], "from": "16:00", "to": "08:00"}}),
    ("from equals to", {"time_window": {"days": [1], "from": "08:00", "to": "08:00"}}),
    ("all false", {"time_window": {"all": False}}),
    ("window extra key", {"time_window": {"all": True, "days": [1]}}),
    ("latitude", {"lat": 91}),
    ("longitude", {"lon": -181}),
    ("missing coordinates", {"lat": None}),
    ("unknown field", {"colour": "red"}),
]


@pytest.mark.parametrize(("case", "change"), INVALID_CREATE, ids=[c for c, _ in INVALID_CREATE])
async def test_invalid_create_is_422(env: Env, case: str, change: dict[str, Any]) -> None:
    me = await env.device()
    body = place(**change)
    body = {k: v for k, v in body.items() if v is not None}
    r = await env.client.post("/v1/places", headers=me, json=body)
    assert r.status_code == 422, (case, r.text)
    assert r.json()["error"] == "invalid_request"
    assert await env.scalar("SELECT count(*) FROM places") == 0


@pytest.mark.parametrize(
    "change",
    [
        {"label": None},
        {"radius_m": 250},
        {"lat": 59.9},
        {"categories": []},
        {"push": None},
        {"template": "x"},
    ],
)
async def test_invalid_update_is_422(env: Env, change: dict[str, Any]) -> None:
    me = await env.device()
    pid = (await env.client.post("/v1/places", headers=me, json=place())).json()["id"]
    r = await env.client.patch(f"/v1/places/{pid}", headers=me, json=change)
    assert r.status_code == 422, r.text


async def test_eleventh_place_is_409(env: Env) -> None:
    me = await env.device()
    for i in range(10):
        r = await env.client.post("/v1/places", headers=me, json=place(label=f"Sted {i}"))
        assert r.status_code == 201
    assert env.kv.calls == 1  # the point lookup is cached
    r = await env.client.post("/v1/places", headers=me, json=place(label="Sted 11"))
    assert r.status_code == 409 and r.json()["error"] == "place_limit"
    assert await env.scalar("SELECT count(*) FROM places") == 10
    # Another device has its own 10.
    assert (await env.client.post("/v1/places", headers=await env.device(), json=place())).status_code == 201
    # After a delete there is room again.
    pid = (await env.client.get("/v1/places", headers=me)).json()[0]["id"]
    await env.client.delete(f"/v1/places/{pid}", headers=me)
    assert (await env.client.post("/v1/places", headers=me, json=place())).status_code == 201


async def test_place_outside_the_ingested_fylker_is_saved_but_not_covered(env: Env) -> None:
    me = await env.device()
    r = await env.client.post(
        "/v1/places", headers=me, json=place(label="Hytta", template="hytte", **TRONDHEIM)
    )
    assert r.status_code == 201
    assert r.json()["kommunenummer"] == "5001" and r.json()["covered"] is False


async def test_place_in_no_municipality(env: Env) -> None:
    me = await env.device()
    r = await env.client.post("/v1/places", headers=me, json=place(label="Båten", **NORDSJOEN))
    assert r.status_code == 201
    assert r.json()["kommunenummer"] is None and r.json()["covered"] is False
    key = f"kpkt|{NORDSJOEN['lat']:.5f}|{NORDSJOEN['lon']:.5f}"
    # «In no municipality» is a real answer, so it is cached (as NULL).
    assert await env.scalar("SELECT count(*) FROM geocode_cache WHERE key = :k AND value IS NULL", k=key) == 1


async def test_kartverket_failure_on_create_is_502_and_saves_nothing(env: Env) -> None:
    me = await env.device()
    env.kv.fail = True
    r = await env.client.post("/v1/places", headers=me, json=place())
    assert r.status_code == 502 and r.json()["error"] == "kartverket_unavailable"
    assert await env.scalar("SELECT count(*) FROM places") == 0
    assert await env.scalar("SELECT count(*) FROM geocode_cache WHERE key LIKE 'kpkt|%'") == 0


async def test_moving_a_place_looks_up_its_municipality_again(env: Env) -> None:
    me = await env.device()
    pid = (await env.client.post("/v1/places", headers=me, json=place())).json()["id"]
    r = await env.client.patch(f"/v1/places/{pid}", headers=me, json=TRONDHEIM)
    assert r.json()["kommunenummer"] == "5001" and r.json()["covered"] is False
    env.kv.fail = True
    r = await env.client.patch(f"/v1/places/{pid}", headers=me, json=TOYEN_SKOLE | {"lat": 59.91484})
    assert r.status_code == 502
    assert await env.scalar("SELECT kommunenummer FROM places WHERE id = :id", id=pid) == "5001"


async def test_delete_place_removes_its_notifications_and_feedback(env: Env) -> None:
    me = await env.device()
    keep = (await env.client.post("/v1/places", headers=me, json=place(label="A"))).json()["id"]
    gone = (await env.client.post("/v1/places", headers=me, json=place(label="B"))).json()["id"]
    await env.db.execute(
        text(
            "INSERT INTO events (id, category, severity, first_message_at, last_message_at, raw) "
            "VALUES ('ev-1', 'Brann', 'severe', now(), now(), '{}')"
        )
    )
    for pid in (keep, gone):
        await env.db.execute(
            text("INSERT INTO notifications (place_id, event_id, kind) VALUES (:p, 'ev-1', 'push')"),
            {"p": pid},
        )
        await env.db.execute(
            text("INSERT INTO placement_feedback (event_id, place_id) VALUES ('ev-1', :p)"), {"p": pid}
        )
    assert (await env.client.delete(f"/v1/places/{gone}", headers=me)).status_code == 204
    assert await env.scalar("SELECT count(*) FROM notifications WHERE place_id = :p", p=gone) == 0
    assert await env.scalar("SELECT count(*) FROM placement_feedback WHERE place_id = :p", p=gone) == 0
    assert await env.scalar("SELECT count(*) FROM notifications WHERE place_id = :p", p=keep) == 1
    assert await env.scalar("SELECT count(*) FROM placement_feedback WHERE place_id = :p", p=keep) == 1


async def test_places_need_a_device(env: Env) -> None:
    assert (await env.client.get("/v1/places")).status_code == 401
    assert (await env.client.post("/v1/places", json=place())).status_code == 401


# --- geocode search ------------------------------------------------------------------------


async def search(env: Env, q: str, headers: dict[str, str]) -> httpx.Response:
    return await env.client.get("/v1/geocode/search", params={"q": q}, headers=headers)


async def test_search_toyen_skole(env: Env) -> None:
    me = await env.device()
    r = await search(env, "Tøyen skole", me)
    assert r.status_code == 200, r.text
    first = r.json()[0]
    assert first == {
        "kind": "sted",
        "label": "Tøyen skole",
        "secondary": "Skole, Oslo",
        "lat": 59.91483,
        "lon": 10.77318,
        "kommunenummer": "0301",
        "covered": True,
    }
    # Both sources are cached per query, and a second search makes no request.
    keys = {f"sok|adr|{norm('Tøyen skole')}", f"sok|sted|{norm('Tøyen skole')}"}
    assert await env.scalar("SELECT count(*) FROM geocode_cache WHERE key = ANY(:k)", k=list(keys)) == 2
    calls = env.kv.calls
    assert (await search(env, "  tøyen   SKOLE ", me)).json()[0]["label"] == "Tøyen skole"
    assert env.kv.calls == calls


async def test_search_holandsgata_1(env: Env) -> None:
    me = await env.device()
    r = await search(env, "Hølandsgata 1", me)
    assert r.status_code == 200
    results = r.json()
    addresses = [x["label"] for x in results if x["kind"] == "adresse"]
    # The query's house number first, then the rest in street order.
    assert addresses[:4] == ["Hølandsgata 1A", "Hølandsgata 1B", "Hølandsgata 1C", "Hølandsgata 1D"]
    assert addresses[4:] == ["Hølandsgata 10", "Hølandsgata 14"]
    assert results[0]["kind"] == "adresse"  # a query with a digit lists addresses first
    assert results[0]["secondary"] == "0655 Oslo"
    assert results[0]["kommunenummer"] == "0301" and results[0]["covered"] is True


async def test_search_ranks_the_oslo_area_above_namesakes(env: Env) -> None:
    me = await env.device()
    results = (await search(env, "Tøyen", me)).json()
    assert results[0]["kind"] == "sted"
    assert (results[0]["label"], results[0]["secondary"]) == ("Tøyen", "Tettbebyggelse, Oslo")
    exact = [x for x in results if x["kind"] == "sted" and x["label"] == "Tøyen"]
    inexact = [x for x in results if x["kind"] == "sted" and x["label"] != "Tøyen"]
    assert results.index(exact[-1]) < results.index(inexact[0])  # exact names first
    assert len(results) <= 10


async def test_search_kartverket_failure_is_502_and_caches_nothing(env: Env) -> None:
    me = await env.device()
    env.kv.fail = True
    r = await search(env, "Tøyen skole", me)
    assert r.status_code == 502 and r.json()["error"] == "kartverket_unavailable"
    assert await env.scalar("SELECT count(*) FROM geocode_cache WHERE key LIKE 'sok|%'") == 0
    env.kv.fail = False
    assert (await search(env, "Tøyen skole", me)).status_code == 200  # retried, not a cached failure


async def test_search_cache_expires(env: Env) -> None:
    me = await env.device()
    await search(env, "Tøyen skole", me)
    await env.db.execute(text("UPDATE geocode_cache SET fetched_at = now() - interval '31 days'"))
    calls = env.kv.calls
    assert (await search(env, "Tøyen skole", me)).status_code == 200
    assert env.kv.calls == calls + 2


async def test_search_is_rate_limited_per_device(env: Env) -> None:
    me, other = await env.device(), await env.device()
    for _ in range(5):
        assert (await search(env, "Tøyen skole", me)).status_code == 200
    r = await search(env, "Tøyen skole", me)
    assert r.status_code == 429 and int(r.headers["Retry-After"]) > 0
    assert (await search(env, "Tøyen skole", other)).status_code == 200


@pytest.mark.parametrize("q", ["", "T", " T ", "T*", "x" * 101])
async def test_search_query_too_short_or_long_is_422(env: Env, q: str) -> None:
    me = await env.device()
    assert (await search(env, q, me)).status_code == 422
    assert env.kv.calls == 0


async def test_search_needs_a_device(env: Env) -> None:
    assert (await search(env, "Tøyen skole", {})).status_code == 401
