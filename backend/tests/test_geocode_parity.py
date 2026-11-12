"""Pipeline parity: the port's placement equals the reference script's `plasser()` result,
given the same aliases and the same recorded Kartverket answers.

Inputs: the Appendix C fixtures (one test each), and every recorded Oslo Politiloggen thread
(tests/fixtures/politiloggen/quarter.json; the script reads it with its own `trad_til_rad`,
the port through app.ingest). The plan's bar for threads is ≥ 99 % identical.
"""

from __future__ import annotations

import os
from typing import Any

import httpx
import pytest
import respx
from sqlalchemy.ext.asyncio import AsyncConnection

from app.geocode import places
from app.geocode.cache import CachedKartverket, GeocodeCache
from app.geocode.pipeline import METHOD_NAMES, Geocoder, Placement
from app.ingest.politiloggen import parse_thread
from tests.appendix_c import FIXTURES, KNR, KOMMUNE, Fixture
from tests.kartverket_replay import load_all, replay_handler, request_key
from tests.kartverket_samples import FakeTime, make_client
from tests.politiloggen_fixtures import raw_threads_in, register
from tests.test_text_parity import ref

RECORDS = load_all()


def patch_script(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """Make the script answer from the recordings, with our alias table and no cache file."""

    def replay_get_json(url: str, params: dict, tries: int = 5) -> dict:
        rec = RECORDS.get(request_key(url, params))
        assert rec is not None, f"script made an unrecorded request: {url} {params}"
        if rec["status"] in (400, 404):
            resp = httpx.Response(rec["status"], request=httpx.Request("GET", url))
            raise ref.requests.HTTPError(response=resp)
        return rec["body"]

    monkeypatch.setattr(ref, "get_json", replay_get_json)
    monkeypatch.setattr(ref, "STED_ALIAS", places.STED_ALIAS)
    monkeypatch.setattr(ref.time, "sleep", lambda s: None)
    monkeypatch.setattr(ref.Geokoder, "lagre", lambda self: None)
    monkeypatch.chdir(tmp_path)  # the script's JSON cache file is relative to the cwd


def script_placement(monkeypatch: pytest.MonkeyPatch, tmp_path, f: Fixture) -> dict[str, Any]:
    patch_script(monkeypatch, tmp_path)
    return ref.plasser({"omrade": f.area, "tekst": f.text}, ref.Geokoder(KNR), KOMMUNE)


def as_tuple(p: Placement) -> tuple[Any, ...]:
    return (p.method, p.match, p.lat, p.lon, p.uncertainty_m, p.detail)


def script_tuple(res: dict[str, Any]) -> tuple[Any, ...]:
    return (
        METHOD_NAMES[res["metode"]],
        res["treff"],
        res["lat"],
        res["lon"],
        res["usikkerhet_m"],
        res.get("detalj") or "",
    )


@pytest.mark.parametrize("f", FIXTURES, ids=[f"c{f.nr:02d}" for f in FIXTURES])
async def test_pipeline_matches_script(
    monkeypatch: pytest.MonkeyPatch, tmp_path: os.PathLike, db: AsyncConnection, f: Fixture
) -> None:
    expected = script_placement(monkeypatch, tmp_path, f)

    async with (
        respx.mock(assert_all_mocked=True, assert_all_called=False) as router,
        httpx.AsyncClient() as http,
    ):
        router.route().mock(side_effect=replay_handler(RECORDS))
        got: Placement = await Geocoder(
            CachedKartverket(make_client(http, FakeTime()), GeocodeCache(db)), KNR, KOMMUNE
        ).place(f.area, f.text)

    assert as_tuple(got) == script_tuple(expected)


OSLO_THREADS = raw_threads_in(KNR)


async def test_pipeline_matches_script_on_recorded_oslo_threads(
    monkeypatch: pytest.MonkeyPatch, tmp_path: os.PathLike, db: AsyncConnection
) -> None:
    assert len(OSLO_THREADS) >= 300, "re-record: uv run python -m scripts.record_politiloggen"
    kommune = register().resolve("Oslo")
    assert kommune is not None and (kommune.nummer, kommune.navn) == (KNR, KOMMUNE)

    patch_script(monkeypatch, tmp_path)
    script_geo = ref.Geokoder(KNR)

    diffs: list[str] = []
    async with (
        respx.mock(assert_all_mocked=True, assert_all_called=False) as router,
        httpx.AsyncClient() as http,
    ):
        router.route().mock(side_effect=replay_handler(RECORDS))
        geocoder = Geocoder(
            CachedKartverket(make_client(http, FakeTime()), GeocodeCache(db)), kommune.nummer, kommune.navn
        )
        for raw in OSLO_THREADS:
            expected = script_tuple(ref.plasser(ref.trad_til_rad(raw), script_geo, KOMMUNE))
            t = parse_thread(raw)
            assert t is not None
            got = as_tuple(await geocoder.place(t.area, t.text))
            if got != expected:
                diffs.append(f"{t.id} area={t.area!r}\n  port:   {got}\n  script: {expected}")

    rate = 1 - len(diffs) / len(OSLO_THREADS)
    print(f"\nparity on {len(OSLO_THREADS)} Oslo threads: {rate:.2%} identical")
    for d in diffs:
        print(d)
    assert rate >= 0.99, "\n".join(diffs)


def test_aliases_extend_the_script() -> None:
    """Our alias table keeps every script alias unchanged and only adds decided ones."""
    for key, value in ref.STED_ALIAS.items():
        assert places.STED_ALIAS[key] == value
    assert set(places.STED_ALIAS) - set(ref.STED_ALIAS) == {("0301", "rosenhoff")}
