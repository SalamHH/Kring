"""Kartverket client + Postgres cache (spec §9.4; Appendix C #15)."""

from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
import pytest
import respx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.geocode.cache import CachedKartverket, GeocodeCache
from app.geocode.kartverket import KartverketClient
from tests.kartverket_samples import (
    ADRESSE_URL,
    FURUSET,
    STEDSNAVN_URLS,
    FakeTime,
    adresser,
    make_client,
)

KNR = "0301"


@pytest.fixture
def fake() -> FakeTime:
    return FakeTime()


@pytest.fixture
async def router() -> AsyncIterator[respx.MockRouter]:
    async with respx.mock(assert_all_called=False, assert_all_mocked=True) as r:
        yield r


@pytest.fixture
async def client(fake: FakeTime, router: respx.MockRouter) -> AsyncIterator[KartverketClient]:
    async with httpx.AsyncClient() as http:
        yield make_client(http, fake)


@pytest.fixture
def geo(client: KartverketClient, db: AsyncConnection) -> CachedKartverket:
    return CachedKartverket(client, GeocodeCache(db))


async def cache_row(db: AsyncConnection, key: str) -> tuple[bool, str | None]:
    row = (await db.execute(text("SELECT value::text FROM geocode_cache WHERE key = :k"), {"k": key})).first()
    return (row is not None, row[0] if row else None)


# --- successful lookups are cached ---------------------------------------------------------


async def test_points_are_parsed_and_cached(geo: CachedKartverket, router: respx.MockRouter) -> None:
    route = router.get(ADRESSE_URL).mock(
        return_value=httpx.Response(200, json=adresser((59.9234567, 10.7712345), (59.92, 10.77)))
    )
    first = await geo.adresse_punkter("Trondheimsveien", KNR)
    second = await geo.adresse_punkter("trondheimsveien ", KNR)  # same normalised key
    assert first == second == [[59.923457, 10.771235], [59.92, 10.77]]
    assert route.call_count == 1
    assert (geo.misses, geo.hits, geo.failures) == (1, 1, 0)
    params = route.calls.last.request.url.params
    assert dict(params) == {
        "adressenavn": "Trondheimsveien",
        "kommunenummer": KNR,
        "treffPerSide": "1000",
        "utkoordsys": "4258",
    }


async def test_empty_result_is_cached_as_not_found(
    geo: CachedKartverket, router: respx.MockRouter, db: AsyncConnection
) -> None:
    route = router.get(ADRESSE_URL).mock(return_value=httpx.Response(200, json={"adresser": []}))
    assert await geo.adresse_punkter("Finnesikkeveien", KNR) is None
    assert await geo.adresse_punkter("Finnesikkeveien", KNR) is None
    assert route.call_count == 1
    assert await cache_row(db, f"adrp|{KNR}|finnesikkeveien") == (True, None)


@pytest.mark.parametrize("status", [400, 404])
async def test_400_404_cached_as_not_found(
    geo: CachedKartverket, router: respx.MockRouter, db: AsyncConnection, status: int
) -> None:
    route = router.get(ADRESSE_URL).mock(return_value=httpx.Response(status))
    assert await geo.adresse_punkter("Ugyldig", KNR) is None
    assert await geo.adresse_punkter("Ugyldig", KNR) is None
    assert route.call_count == 1  # no retry, and the second call is a cache hit
    assert await cache_row(db, f"adrp|{KNR}|ugyldig") == (True, None)


async def test_exact_address_with_letter(geo: CachedKartverket, router: respx.MockRouter) -> None:
    route = router.get(ADRESSE_URL).mock(
        return_value=httpx.Response(200, json=adresser((59.91, 10.75), tekst="Steenstrups gate 1B"))
    )
    res = await geo.adresse_eksakt("Steenstrups gate", "1", "b", KNR)
    assert res == {
        "lat": 59.91,
        "lon": 10.75,
        "usikkerhet_m": 25.0,
        "kilde": "adresse",
        "detalj": "Steenstrups gate 1B",
    }
    assert dict(route.calls.last.request.url.params)["bokstav"] == "B"
    assert await geo.cache.get(f"adrn|{KNR}|steenstrups gate|1b") == res


# --- failures are never cached (§9.4, Appendix C #15) -----------------------------------------


async def test_c15_http_429_returns_none_not_cached_retried_next_cycle(
    geo: CachedKartverket, router: respx.MockRouter, db: AsyncConnection, fake: FakeTime
) -> None:
    route = router.get(ADRESSE_URL).mock(return_value=httpx.Response(429))
    assert await geo.adresse_punkter("Trondheimsveien", KNR) is None
    assert route.call_count == 3  # first try + 2 retries
    assert fake.sleeps == [1.0, 2.0]
    assert geo.failures == 1
    assert await cache_row(db, f"adrp|{KNR}|trondheimsveien") == (False, None)

    # next cycle: the API has recovered, and the lookup is tried again
    route.mock(return_value=httpx.Response(200, json=adresser((59.92, 10.77))))
    assert await geo.adresse_punkter("Trondheimsveien", KNR) == [[59.92, 10.77]]
    assert route.call_count == 4
    assert (await cache_row(db, f"adrp|{KNR}|trondheimsveien"))[0] is True


@pytest.mark.parametrize(
    "failure",
    [
        httpx.Response(500),
        httpx.Response(503),
        httpx.ReadTimeout("timed out"),
        httpx.ConnectError("connection refused"),
    ],
    ids=["500", "503", "timeout", "connect-error"],
)
async def test_transient_failures_not_cached(
    geo: CachedKartverket, router: respx.MockRouter, db: AsyncConnection, failure: object
) -> None:
    route = router.get(ADRESSE_URL)
    if isinstance(failure, httpx.Response):
        route.mock(return_value=failure)
    else:
        route.mock(side_effect=failure)
    assert await geo.adresse_eksakt("Trondheimsveien", "33", "", KNR) is None
    assert route.call_count == 3
    assert geo.failures == 1
    assert await cache_row(db, f"adrn|{KNR}|trondheimsveien|33") == (False, None)


async def test_retry_then_success(geo: CachedKartverket, router: respx.MockRouter, fake: FakeTime) -> None:
    route = router.get(ADRESSE_URL).mock(
        side_effect=[httpx.Response(502), httpx.Response(200, json=adresser((59.9, 10.7)))]
    )
    assert await geo.adresse_punkter("Storgata", KNR) == [[59.9, 10.7]]
    assert route.call_count == 2
    assert fake.sleeps == [1.0]
    assert geo.failures == 0


async def test_other_http_errors_fail_without_retry(
    geo: CachedKartverket, router: respx.MockRouter, db: AsyncConnection
) -> None:
    route = router.get(ADRESSE_URL).mock(return_value=httpx.Response(403))
    assert await geo.adresse_punkter("Storgata", KNR) is None
    assert route.call_count == 1
    assert geo.failures == 1
    assert (await cache_row(db, f"adrp|{KNR}|storgata"))[0] is False


async def test_invalid_json_is_a_failure(geo: CachedKartverket, router: respx.MockRouter) -> None:
    router.get(ADRESSE_URL).mock(return_value=httpx.Response(200, text="<html>oops</html>"))
    assert await geo.adresse_punkter("Storgata", KNR) is None
    assert geo.failures == 1


# --- spacing ------------------------------------------------------------------------------------


async def test_calls_are_spaced_at_least_150_ms(
    client: KartverketClient, router: respx.MockRouter, fake: FakeTime
) -> None:
    router.get(ADRESSE_URL).mock(return_value=httpx.Response(200, json=adresser((59.9, 10.7))))
    await client.adresse_punkter("A-veien", KNR)
    await client.adresse_punkter("B-veien", KNR)
    fake.now += 0.10  # 100 ms pass on their own
    await client.adresse_punkter("C-veien", KNR)
    fake.now += 1.0  # long gap: no wait needed
    await client.adresse_punkter("D-veien", KNR)
    assert fake.sleeps == [0.15, 0.05]


# --- place names ------------------------------------------------------------------------------


async def test_c10_place_name_prefers_area_over_bus_stop(
    geo: CachedKartverket, router: respx.MockRouter
) -> None:
    route = router.get(STEDSNAVN_URLS[0]).mock(return_value=httpx.Response(200, json=FURUSET))
    res = await geo.stedsnavn("Furuset", KNR)
    assert res == {
        "lat": 59.939,
        "lon": 10.896,
        "usikkerhet_m": 1000.0,
        "kilde": "stedsnavn",
        "detalj": "tettbebyggelse",
    }
    assert dict(route.calls.last.request.url.params) == {
        "sok": "Furuset",
        "knr": KNR,
        "utkoordsys": "4258",
        "treffPerSide": "25",
        "fuzzy": "false",
    }


async def test_place_name_falls_back_to_second_url(geo: CachedKartverket, router: respx.MockRouter) -> None:
    first = router.get(STEDSNAVN_URLS[0]).mock(return_value=httpx.Response(500))
    second = router.get(STEDSNAVN_URLS[1]).mock(return_value=httpx.Response(200, json=FURUSET))
    assert (await geo.stedsnavn("Furuset", KNR))["detalj"] == "tettbebyggelse"
    assert (first.call_count, second.call_count) == (3, 1)


async def test_place_name_no_match_is_cached(
    geo: CachedKartverket, router: respx.MockRouter, db: AsyncConnection
) -> None:
    router.get(STEDSNAVN_URLS[0]).mock(return_value=httpx.Response(200, json={"navn": []}))
    assert await geo.stedsnavn("Ingensteds", KNR) is None
    assert await cache_row(db, f"sted4|{KNR}|ingensteds") == (True, None)


async def test_place_name_404_on_all_urls_is_not_cached(
    geo: CachedKartverket, router: respx.MockRouter, db: AsyncConnection
) -> None:
    """Script behaviour (the script wins, decided 2026-11-12): for place names, an HTTP error
    on every URL, even 404, is a failed lookup and is retried next cycle."""
    for url in STEDSNAVN_URLS:
        router.get(url).mock(return_value=httpx.Response(404))
    assert await geo.stedsnavn("Furuset", KNR) is None
    assert geo.failures == 1
    assert (await cache_row(db, f"sted4|{KNR}|furuset"))[0] is False
