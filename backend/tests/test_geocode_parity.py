"""Pipeline parity: the port's placement equals the reference script's `plasser()` result,
given the same aliases and the same recorded Kartverket answers.

Inputs: the Appendix C fixtures (one test each), and every recorded Oslo and Akershus
Politiloggen thread (tests/fixtures/politiloggen/quarter.json; the script reads it with its
own `trad_til_rad`, the port through app.ingest), each geocoded in its own municipality.
The plan's bar for threads is ≥ 99 % identical, checked for Oslo and Akershus separately.
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
from app.geocode.pipeline import METHOD_NAMES, TILLEGG_METHODS, Geocoder, Placement
from app.ingest.politiloggen import parse_thread
from tests.appendix_c import FIXTURES, KNR, KOMMUNE, Fixture
from tests.kartverket_replay import load_all, replay_handler, request_key
from tests.kartverket_samples import FakeTime, make_client
from tests.politiloggen_fixtures import scoped_raw_threads
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


def same_as_script(got: tuple[Any, ...], expected: tuple[Any, ...]) -> bool:
    """The port's additions (app.geocode.tillegg) only run where the script gives up, so there
    the script's answer must be «municipality only»; everywhere else the answers are identical."""
    if got[0] in TILLEGG_METHODS:
        return expected[0] == "kommune"
    return got == expected


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

    assert same_as_script(as_tuple(got), script_tuple(expected))


SCOPED_THREADS = scoped_raw_threads()
MIN_THREADS = {"03": 300, "32": 500}  # Oslo, Akershus; below this the recording is too thin


@pytest.mark.parametrize("fylke", ["03", "32"], ids=["oslo", "akershus"])
async def test_pipeline_matches_script_on_recorded_threads(
    monkeypatch: pytest.MonkeyPatch, tmp_path: os.PathLike, db: AsyncConnection, fylke: str
) -> None:
    """Each thread is geocoded in its own municipality, by the script and by the port."""
    threads = [(raw, k) for raw, k in SCOPED_THREADS if k.nummer[:2] == fylke]
    assert len(threads) >= MIN_THREADS[fylke], "re-record: uv run python -m scripts.record_politiloggen"

    patch_script(monkeypatch, tmp_path)
    script_geos: dict[str, Any] = {}

    diffs: list[str] = []
    async with (
        respx.mock(assert_all_mocked=True, assert_all_called=False) as router,
        httpx.AsyncClient() as http,
    ):
        router.route().mock(side_effect=replay_handler(RECORDS))
        cached = CachedKartverket(make_client(http, FakeTime()), GeocodeCache(db))
        for raw, k in threads:
            script_geo = script_geos.setdefault(k.nummer, ref.Geokoder(k.nummer))
            expected = script_tuple(ref.plasser(ref.trad_til_rad(raw), script_geo, k.navn))
            t = parse_thread(raw)
            assert t is not None
            got = as_tuple(await Geocoder(cached, k.nummer, k.navn).place(t.area, t.text))
            if not same_as_script(got, expected):
                diffs.append(f"{t.id} {k.navn} area={t.area!r}\n  port:   {got}\n  script: {expected}")

    rate = 1 - len(diffs) / len(threads)
    print(f"\nparity on {len(threads)} threads in {len(script_geos)} municipalities: {rate:.2%} identical")
    for d in diffs:
        print(d)
    assert rate >= 0.99, "\n".join(diffs)


def test_aliases_extend_the_script() -> None:
    """Our alias table keeps every script alias unchanged and only adds decided ones."""
    for key, value in ref.STED_ALIAS.items():
        assert places.STED_ALIAS[key] == value
    assert set(places.STED_ALIAS) - set(ref.STED_ALIAS) == {("0301", "rosenhoff")}
