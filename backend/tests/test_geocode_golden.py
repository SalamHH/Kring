"""Appendix C golden fixtures (spec §9.5 quality gate): the full pipeline, offline.

Kartverket answers come from tests/fixtures/kartverket (recorded) except #10 (hand-built
response) and #15 (HTTP 429). Each test asserts what the Expected column states, no more
(decided 2026-11-12).
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
import pytest
import respx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.classify.rules import is_control, precision_tier, round_uncertainty
from app.geocode.cache import CachedKartverket, GeocodeCache
from app.geocode.pipeline import Geocoder, Placement
from tests.appendix_c import FIXTURES, KNR, KOMMUNE
from tests.kartverket_replay import replay_handler
from tests.kartverket_samples import FURUSET, STEDSNAVN_URLS, FakeTime, make_client

BY_NR = {f.nr: f for f in FIXTURES}


@pytest.fixture
async def geocoder(db: AsyncConnection) -> AsyncIterator[Geocoder]:
    """A geocoder whose Kartverket calls are answered from the recordings only."""
    # assert_all_called=False: some fixtures (e.g. #11, an alias) need no HTTP at all.
    async with (
        respx.mock(assert_all_mocked=True, assert_all_called=False) as router,
        httpx.AsyncClient() as http,
    ):
        router.route().mock(side_effect=replay_handler())
        geo = CachedKartverket(make_client(http, FakeTime()), GeocodeCache(db))
        yield Geocoder(geo, KNR, KOMMUNE)


async def place(geocoder: Geocoder, nr: int) -> Placement:
    f = BY_NR[nr]
    return await geocoder.place(f.area, f.text)


def tier(p: Placement) -> str:
    return precision_tier(round_uncertainty(p.uncertainty_m))


async def test_c01_exact_address_not_floor_number(geocoder: Geocoder) -> None:
    p = await place(geocoder, 1)
    assert p.method == "adresse"
    assert p.match == "Trondheimsveien 33"
    assert tier(p) == "gate"


async def test_c02_long_street_limited_to_area(geocoder: Geocoder) -> None:
    p = await place(geocoder, 2)
    assert p.method == "gate_omrade"
    assert p.match == "Trondheimsveien ved Rosenhoff"
    assert p.uncertainty_m is not None and p.uncertainty_m < 1000


async def test_c03_crossing(geocoder: Geocoder) -> None:
    p = await place(geocoder, 3)
    assert p.method == "kryss"
    assert p.match == "Louises gate x Ullevålsveien"
    assert p.uncertainty_m is not None and 75 <= p.uncertainty_m <= 150


async def test_c04_direction_filter(geocoder: Geocoder) -> None:
    p = await place(geocoder, 4)
    assert "Maridalsveien" not in p.match


async def test_c05_two_word_street_address(geocoder: Geocoder) -> None:
    p = await place(geocoder, 5)
    assert p.method == "adresse"
    assert p.detail.lower() == "økern torgvei 1"  # the official address text from Kartverket


async def test_c06_whole_area_street_first(geocoder: Geocoder) -> None:
    p = await place(geocoder, 6)
    assert p.method == "gate_area"
    assert p.match == "Nedre Kalbakkvei"


async def test_c07_long_street_limited_to_ulvoya(geocoder: Geocoder) -> None:
    p = await place(geocoder, 7)
    assert p.method == "gate_omrade"
    assert p.match == "Mosseveien ved Ulvøya"


def test_c08_planned_control() -> None:
    f = BY_NR[8]
    assert is_control(f.category, f.text) is True


async def test_c09_road_prefix_stripped_place_name(geocoder: Geocoder) -> None:
    p = await place(geocoder, 9)
    assert p.method == "stedsnavn"
    assert p.match == "Furuset"


async def test_c10_area_type_preferred_over_bus_stop(db: AsyncConnection) -> None:
    async with respx.mock(assert_all_mocked=True) as router, httpx.AsyncClient() as http:
        router.get(STEDSNAVN_URLS[0]).mock(return_value=httpx.Response(200, json=FURUSET))
        geocoder = Geocoder(CachedKartverket(make_client(http, FakeTime()), GeocodeCache(db)), KNR, KOMMUNE)
        p = await geocoder.place("Furuset", "")
    assert p.method == "stedsnavn"
    assert p.detail == "tettbebyggelse"
    assert p.uncertainty_m == 1000


async def test_c11_alias_oslo_sentrum(geocoder: Geocoder) -> None:
    p = await place(geocoder, 11)
    assert p.detail == "alias: Oslo sentrum"
    assert p.uncertainty_m == 1200


async def test_c12_speed_limit_not_house_number(geocoder: Geocoder) -> None:
    p = await place(geocoder, 12)
    assert p.method != "adresse"


async def test_c13_crossing_with_spelling_variant(geocoder: Geocoder) -> None:
    p = await place(geocoder, 13)
    assert p.method == "kryss"
    assert p.match == "Hausmanns gate x Storgata"


async def test_c14_downgrade_to_place_name(geocoder: Geocoder) -> None:
    p = await place(geocoder, 14)
    assert p.method == "stedsnavn"
    assert p.match == "Bjørndal"


async def test_c15_429_no_result_not_cached(db: AsyncConnection) -> None:
    async with respx.mock(assert_all_mocked=True) as router, httpx.AsyncClient() as http:
        router.route().mock(return_value=httpx.Response(429))
        geo = CachedKartverket(make_client(http, FakeTime()), GeocodeCache(db))
        p = await Geocoder(geo, KNR, KOMMUNE).place("Bjørndal", "Ran av en person sør for Enebakkveien")
    assert not p.has_point
    assert p.method == "kommune"
    assert geo.failures > 0
    assert (await db.execute(text("SELECT count(*) FROM geocode_cache"))).scalar() == 0


async def test_second_run_uses_cache_only(db: AsyncConnection) -> None:
    """After one pass over the fixtures, a second pass makes no HTTP requests."""
    async with respx.mock(assert_all_mocked=True) as router, httpx.AsyncClient() as http:
        route = router.route().mock(side_effect=replay_handler())
        geocoder = Geocoder(CachedKartverket(make_client(http, FakeTime()), GeocodeCache(db)), KNR, KOMMUNE)
        first = [await geocoder.place(f.area, f.text) for f in FIXTURES]
        calls = route.call_count
        second = [await geocoder.place(f.area, f.text) for f in FIXTURES]
    assert calls > 0
    assert route.call_count == calls
    assert first == second
