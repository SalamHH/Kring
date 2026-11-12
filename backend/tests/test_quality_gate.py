"""Quality gate (spec §9.5): offline replay of the recorded quarter.

Oslo is gated: of non-control incidents, ≥ 60 % within 1 000 m and ≥ 25 % within 500 m.
Akershus is reported but not gated (decided 2026-11-12); it has a regression floor at the
level reached by the Akershus pass (app.geocode.tillegg), not a target. The fixed subset is the recorded
quarter in tests/fixtures/politiloggen/quarter.json; re-recording it changes the numbers.
"""

from __future__ import annotations

import asyncio

import pytest

from tests.quality import Row, replay, summarise

GATE_1000 = 0.60
GATE_500 = 0.25
AKERSHUS_FLOOR_1000 = 0.34
AKERSHUS_MAX_UNPLACED = 0.18


@pytest.fixture(scope="module")
def rows() -> list[Row]:
    return asyncio.run(replay())  # once per module, on its own loop


def report(name: str, rows: list[Row]) -> str:
    s = summarise(rows)
    return (
        f"{name}: {s.analysed} incidents ({s.controls} controls excluded): "
        f"≤500 m {s.le_500:.1%}, ≤1000 m {s.le_1000:.1%}, unplaced {s.unplaced:.1%}"
    )


def test_oslo_gate(rows: list[Row]) -> None:
    oslo = [r for r in rows if r.knr == "0301"]
    assert len(oslo) >= 300, "re-record: uv run python -m scripts.record_politiloggen"
    s = summarise(oslo)
    print("\n" + report("Oslo", oslo))
    assert s.le_1000 >= GATE_1000, report("Oslo", oslo)
    assert s.le_500 >= GATE_500, report("Oslo", oslo)


def test_akershus_is_reported(rows: list[Row]) -> None:
    akershus = [r for r in rows if r.fylke == "32"]
    assert len(akershus) >= 500
    print("\n" + report("Akershus (floor, not a gate)", akershus))
    s = summarise(akershus)
    assert s.le_1000 >= AKERSHUS_FLOOR_1000, report("Akershus", akershus)
    assert s.unplaced <= AKERSHUS_MAX_UNPLACED, report("Akershus", akershus)
