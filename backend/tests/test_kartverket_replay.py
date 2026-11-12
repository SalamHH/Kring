"""Every recorded Kartverket response replays through the port (same request, so the
recording is found) and gives the same result as the reference script on that body."""

from __future__ import annotations

import httpx
import pytest
import respx

from tests.kartverket_replay import load_all, replay_handler
from tests.kartverket_samples import FakeTime, make_client
from tests.test_kartverket_parity import oracle_with_response
from tests.test_text_parity import ref

RECORDS = load_all()


def test_recordings_exist() -> None:
    assert len(RECORDS) >= 15, "run: uv run python -m scripts.record_kartverket"


@pytest.mark.parametrize("key", RECORDS.keys())
async def test_recording_replays_like_the_script(monkeypatch: pytest.MonkeyPatch, key: str) -> None:
    rec = RECORDS[key]
    p = rec["params"]
    knr = p.get("knr") or p["kommunenummer"]
    if "sok" in p:
        method, args = "stedsnavn", (p["sok"], knr)
        oracle = lambda g: g._stedsnavn_sok(p["sok"])  # noqa: E731
    elif "nummer" in p:
        method, args = "adresse_eksakt", (p["adressenavn"], p["nummer"], p.get("bokstav", ""), knr)
        oracle = lambda g: g._adresse_eksakt(p["adressenavn"], p["nummer"], p.get("bokstav", ""))  # noqa: E731
    else:
        method, args = "adresse_punkter", (p["adressenavn"], knr)
        oracle = lambda g: g._adresse_punkter(p["adressenavn"])  # noqa: E731

    async with respx.mock(assert_all_mocked=True) as router, httpx.AsyncClient() as http:
        router.route().mock(side_effect=replay_handler(RECORDS))
        result = await getattr(make_client(http, FakeTime()), method)(*args)

    assert rec["status"] == 200, "only 200 responses are expected in the recordings"
    oracle_with_response(monkeypatch, rec["body"])
    assert result == oracle(ref.Geokoder(knr))
