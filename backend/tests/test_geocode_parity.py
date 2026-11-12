"""Pipeline parity: for each Appendix C input, the port's placement equals the reference
script's `plasser()` result, given the same aliases and the same recorded Kartverket answers.

Parity on real recorded Politiloggen threads is added in M0 step 6.
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
from tests.appendix_c import FIXTURES, KNR, KOMMUNE, Fixture
from tests.kartverket_replay import load_all, request_key
from tests.kartverket_samples import FakeTime, make_client
from tests.test_text_parity import ref

RECORDS = load_all()


def script_placement(monkeypatch: pytest.MonkeyPatch, tmp_path, f: Fixture) -> dict[str, Any]:
    """Run the script's plasser() with recorded answers and our alias table."""

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
    monkeypatch.chdir(tmp_path)  # the script's JSON cache file is relative to the cwd
    return ref.plasser({"omrade": f.area, "tekst": f.text}, ref.Geokoder(KNR), KOMMUNE)


@pytest.mark.parametrize("f", FIXTURES, ids=[f"c{f.nr:02d}" for f in FIXTURES])
async def test_pipeline_matches_script(
    monkeypatch: pytest.MonkeyPatch, tmp_path: os.PathLike, db: AsyncConnection, f: Fixture
) -> None:
    expected = script_placement(monkeypatch, tmp_path, f)

    async with (
        respx.mock(assert_all_mocked=True, assert_all_called=False) as router,
        httpx.AsyncClient() as http,
    ):
        from tests.kartverket_replay import replay_handler

        router.route().mock(side_effect=replay_handler(RECORDS))
        got: Placement = await Geocoder(
            CachedKartverket(make_client(http, FakeTime()), GeocodeCache(db)), KNR, KOMMUNE
        ).place(f.area, f.text)

    assert got.method == METHOD_NAMES[expected["metode"]]
    assert got.match == expected["treff"]
    assert got.lat == expected["lat"]
    assert got.lon == expected["lon"]
    assert got.uncertainty_m == expected["usikkerhet_m"]
    assert got.detail == (expected.get("detalj") or "")


def test_aliases_extend_the_script() -> None:
    """Our alias table keeps every script alias unchanged and only adds decided ones."""
    for key, value in ref.STED_ALIAS.items():
        assert places.STED_ALIAS[key] == value
    assert set(places.STED_ALIAS) - set(ref.STED_ALIAS) == {("0301", "rosenhoff")}
