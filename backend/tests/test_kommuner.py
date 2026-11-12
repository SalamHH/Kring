"""Municipality name → kommunenummer, the allowed-set filter, and the cached kommuneinfo list."""

from __future__ import annotations

import logging
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import httpx
import pytest
import respx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.ingest.kommuner import KEY, KommuneinfoFailed, KommuneRegister, in_scope, load_register
from app.ingest.politiloggen import parse_page
from app.settings import Settings
from tests.politiloggen_fixtures import kommuner, page_sample, quarter, register

URL = Settings().kommuneinfo_url
ALLOWED = ["03", "32"]


@pytest.mark.parametrize(
    "name, nummer",
    [("Oslo", "0301"), ("oslo", "0301"), (" Bærum ", "3201"), ("Lillestrøm", "3205"),
     ("Nordre Follo", "3207"), ("Tana", "5628"), ("Deatnu", "5628")],  # Norwegian and Sámi names
)  # fmt: skip
def test_resolve(name: str, nummer: str) -> None:
    k = register().resolve(name)
    assert k is not None and k.nummer == nummer


def test_resolve_gives_norwegian_name_for_the_geocoder() -> None:
    k = register().resolve("Deatnu")
    assert k is not None and k.navn == "Tana"


@pytest.mark.parametrize("name", ["Oslo politidistrikt", "Atlantis", "", None, "Våler", "Herøy"])
def test_unknown_or_ambiguous_is_none(name: str | None) -> None:
    assert register().resolve(name) is None


def test_unknown_municipality_warns_once_and_is_skipped(caplog) -> None:
    reg = register()
    page = parse_page(page_sample())
    t = page.threads[0]
    unknown = [replace(t, id=f"x{i}", municipality="Oslo politidistrikt") for i in range(3)]
    oslo = replace(t, id="oslo1", municipality="Oslo")
    with caplog.at_level(logging.WARNING, logger="app.ingest.kommuner"):
        scoped = in_scope([*unknown, oslo], reg, ALLOWED)
    assert [s.thread.id for s in scoped] == ["oslo1"]
    assert scoped[0].kommune.nummer == "0301"
    warns = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warns) == 1
    assert "Oslo politidistrikt" in warns[0].getMessage()


def test_known_municipality_outside_scope_is_skipped_quietly(caplog) -> None:
    page = parse_page(page_sample())
    with caplog.at_level(logging.WARNING, logger="app.ingest.kommuner"):
        scoped = in_scope(page.threads, register(), [])
    assert scoped == []
    resolvable = [t for t in page.threads if register().resolve(t.municipality)]
    assert resolvable  # the sample has known municipalities, none of them warned about
    warned = " ".join(r.getMessage() for r in caplog.records)
    assert all(repr(t.municipality) not in warned for t in resolvable)


def test_recorded_quarter_is_all_in_scope() -> None:
    page = parse_page({"messageThreads": quarter()["threads"]})
    scoped = in_scope(page.threads, register(), ALLOWED)
    assert len(scoped) == len(page.threads)
    assert {s.kommune.nummer[:2] for s in scoped} == {"03", "32"}


def test_register_ignores_bad_rows() -> None:
    reg = KommuneRegister([None, {}, {"kommunenummer": "12", "kommunenavn": "X"}, {"kommunenummer": "0301"},
                           {"kommunenummer": "0301", "kommunenavn": "Oslo"}])  # fmt: skip
    assert len(reg) == 1


# --- cached kommuneinfo -----------------------------------------------------------------------


async def cache_row(db: AsyncConnection):
    return (
        await db.execute(text("SELECT value, fetched_at FROM geocode_cache WHERE key = :k"), {"k": KEY})
    ).first()


async def test_fetches_and_caches(db: AsyncConnection) -> None:
    with respx.mock(assert_all_called=True) as router:
        route = router.get(URL).mock(return_value=httpx.Response(200, json=kommuner()))
        async with httpx.AsyncClient() as http:
            reg = await load_register(db, http, URL)
            again = await load_register(db, http, URL)
    assert route.call_count == 1
    assert reg.resolve("Oslo") == again.resolve("Oslo")
    row = await cache_row(db)
    assert row is not None and len(row[0]) == len(kommuner())


@pytest.mark.parametrize(
    "response",
    [httpx.Response(503), httpx.Response(429), httpx.Response(200, text="<html>"),
     httpx.Response(200, json=[]), httpx.ConnectError("down")],
    ids=["503", "429", "not json", "empty list", "connect error"],
)  # fmt: skip
async def test_failure_is_not_cached(db: AsyncConnection, response) -> None:
    with respx.mock() as router:
        router.get(URL).mock(side_effect=[response])
        async with httpx.AsyncClient() as http:
            with pytest.raises(KommuneinfoFailed):
                await load_register(db, http, URL)
    assert await cache_row(db) is None


async def test_stale_cache_is_refreshed_and_used_if_refresh_fails(db: AsyncConnection) -> None:
    async with httpx.AsyncClient() as http:
        with respx.mock() as router:
            router.get(URL).mock(return_value=httpx.Response(200, json=kommuner()))
            await load_register(db, http, URL)
        later = datetime.now(UTC) + timedelta(days=31)
        with respx.mock() as router:
            route = router.get(URL).mock(return_value=httpx.Response(503))
            reg = await load_register(db, http, URL, now=later)
    assert route.call_count == 1
    k = reg.resolve("Oslo")
    assert k is not None and k.nummer == "0301"
