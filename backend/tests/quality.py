"""Offline replay of the recorded Politiloggen quarter through the geocoder (spec §9.5).

Every recorded Oslo and Akershus thread is placed by the port, offline: Kartverket answers come
from the recordings (tests/fixtures/kartverket) and the cache is in memory. Used by the pytest
quality gate (tests/test_quality_gate.py) and by scripts/m0_report.py.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any

import httpx
import respx

from app.classify.rules import is_control, precision_tier, round_uncertainty
from app.geocode.cache import _MISS, CachedKartverket
from app.geocode.pipeline import Geocoder, Placement
from app.ingest.politiloggen import parse_thread
from tests.kartverket_replay import load_all, replay_handler
from tests.kartverket_samples import FakeTime, make_client
from tests.politiloggen_fixtures import quarter, scoped_raw_threads

STREET_METHODS = ("adresse", "kryss", "gate_area", "gate_tekst", "gate_omrade")


class MemoryCache:
    """GeocodeCache without a database."""

    def __init__(self) -> None:
        self.data: dict[str, Any] = {}

    async def get(self, key: str) -> Any:
        return self.data.get(key, _MISS)

    async def put(self, key: str, value: Any) -> None:
        self.data[key] = value


@dataclass(frozen=True)
class Row:
    id: str
    knr: str
    kommune: str
    category: str
    area: str | None
    text: str
    is_control: bool
    placement: Placement

    @property
    def fylke(self) -> str:
        return self.knr[:2]

    @property
    def uncertainty(self) -> int | None:
        """As stored: rounded half-up; None when there is no point."""
        return round_uncertainty(self.placement.uncertainty_m) if self.placement.has_point else None

    @property
    def tier(self) -> str:
        return precision_tier(self.uncertainty)

    def within(self, metres: int) -> bool:
        return self.uncertainty is not None and self.uncertainty <= metres


async def replay() -> list[Row]:
    rows: list[Row] = []
    async with (
        respx.mock(assert_all_mocked=True, assert_all_called=False) as router,
        httpx.AsyncClient() as http,
    ):
        router.route().mock(side_effect=replay_handler(load_all()))
        cached = CachedKartverket(make_client(http, FakeTime()), MemoryCache())  # type: ignore[arg-type]
        for raw, k in scoped_raw_threads():
            t = parse_thread(raw)
            assert t is not None, raw.get("id")
            p = await Geocoder(cached, k.nummer, k.navn).place(t.area, t.text)
            rows.append(
                Row(t.id, k.nummer, k.navn, t.category, t.area, t.text, is_control(t.category, t.text), p)
            )
    return rows


@dataclass(frozen=True)
class Summary:
    threads: int
    controls: int
    analysed: int
    le_300: float
    le_500: float
    le_1000: float
    le_2000: float
    unplaced: float
    methods: Counter[str]
    tiers: Counter[str]


def summarise(rows: list[Row]) -> Summary:
    analysed = [r for r in rows if not r.is_control]
    n = len(analysed) or 1

    def share(m: int) -> float:
        return sum(r.within(m) for r in analysed) / n

    return Summary(
        threads=len(rows),
        controls=len(rows) - len(analysed),
        analysed=len(analysed),
        le_300=share(300),
        le_500=share(500),
        le_1000=share(1000),
        le_2000=share(2000),
        unplaced=sum(not r.placement.has_point for r in analysed) / n,
        methods=Counter(r.placement.method for r in analysed),
        tiers=Counter(r.tier for r in analysed),
    )


def recorded_at() -> str:
    return str(quarter().get("recorded_at"))
