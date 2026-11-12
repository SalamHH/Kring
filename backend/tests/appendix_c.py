"""Appendix C geocoder fixtures as data: inputs only (expectations live in the tests).

The spec gives excerpts («…»); these are full sentences built around them. All are in
Oslo (0301). #10 (synthetic API response) and #15 (HTTP 429) need no recording.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Fixture:
    nr: int
    area: str | None
    text: str
    category: str = "Andre hendelser"


KNR = "0301"
KOMMUNE = "Oslo"

FIXTURES: list[Fixture] = [
    Fixture(
        1, None, "Nødetatene er på vei til Trondheimsveien 33 etter melding om brann i 3 etasje", "Brann"
    ),
    Fixture(2, "Rosenhoff", "Det har vært et sammenstøt mellom to biler i Trondheimsveien", "Trafikk"),
    Fixture(3, None, "I krysset Louises gate/Ullevålsveien har det vært en trafikkulykke", "Trafikk"),
    Fixture(4, "Tåsentunnelen", "Bilen stoppet i avkjøringsrampen mot Maridalsveien", "Trafikk"),
    Fixture(5, None, "Politiet opplyser at hendelsen er i Økern Torgvei 1"),
    Fixture(6, "Nedre Kalbakkvei", "Melding om bråk i en leilighet", "Ro og orden"),
    Fixture(7, "Mosseveien V/ Ulvøya", "Trafikkulykke med to biler, ingen personskader", "Trafikk"),
    Fixture(8, None, "Politiet har hatt trafikkontroll i Holtegata", "Trafikk"),
    Fixture(9, "E6 Furuset", "Trafikkuhell, to biler involvert", "Trafikk"),
    Fixture(11, "Sentrum", "Slagsmål mellom flere personer", "Ro og orden"),
    Fixture(12, None, "Holtegata hvor fartsgrensen er 30 km/t", "Trafikk"),
    Fixture(13, None, "Trafikkuhell i krysset Hausmannsgate/Storgata", "Trafikk"),
    Fixture(14, "Bjørndal", "Ran av en person sør for Enebakkveien", "Ran"),
]
