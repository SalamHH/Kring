"""Small hand-built Kartverket responses and a test client with a fake clock."""

from __future__ import annotations

from typing import Any

import httpx

from app.geocode.kartverket import KartverketClient

ADRESSE_URL = "https://ws.geonorge.no/adresser/v1/sok"
STEDSNAVN_URLS = [
    "https://ws.geonorge.no/stedsnavn/v1/navn",
    "https://api.kartverket.no/stedsnavn/v1/navn",
]


def adresser(*points: tuple[float, float], tekst: str = "Testveien 1") -> dict[str, Any]:
    return {
        "adresser": [
            {"adressetekst": tekst, "representasjonspunkt": {"lat": lat, "lon": lon, "epsg": "EPSG:4258"}}
            for lat, lon in points
        ]
    }


def stedsnavn_hit(name: str, typ: str, nord: float, ost: float) -> dict[str, Any]:
    return {
        "navneobjekttype": typ,
        "stedsnavn": [{"skrivemåte": name}],
        "representasjonspunkt": {"nord": nord, "øst": ost},
    }


FURUSET = {
    "navn": [
        stedsnavn_hit("Furuset", "Holdeplass", 59.9402, 10.8930),
        stedsnavn_hit("Furuset", "Tettbebyggelse", 59.9390, 10.8960),
        stedsnavn_hit("Furusetveien", "Adressenavn", 59.9400, 10.8900),  # different spelling: ignored
    ]
}


class FakeTime:
    """Monotonic clock that only moves when the client sleeps; records every sleep."""

    def __init__(self) -> None:
        self.now = 1000.0
        self.sleeps: list[float] = []

    def clock(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(round(seconds, 6))
        self.now += seconds


def make_client(http: httpx.AsyncClient, fake: FakeTime) -> KartverketClient:
    return KartverketClient(http, ADRESSE_URL, STEDSNAVN_URLS, sleep=fake.sleep, clock=fake.clock)
