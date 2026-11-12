"""Additions to the geocoder where the script gives up (app.geocode.tillegg, spec §9.2).

Inputs are real area fields and message texts from the recorded quarter.
"""

from __future__ import annotations

import pytest

from app.geocode.text import omradedeler
from app.geocode.tillegg import akseptabel, omrade_kandidater, tekst_kandidater


@pytest.mark.parametrize(
    "area, kommune, kandidater, kommune_nevnt",
    [
        ("E18 Inn Sandvika", "Bærum", ["Sandvika"], False),
        ("E6 Nordgående Kløfta", "Ullensaker", ["Kløfta"], False),
        ("E6 Helsfyr Mot Oslo", "Oslo", ["Helsfyr"], False),
        ("E6 Lindeberg Retning Oslo", "Lillestrøm", ["Lindeberg"], False),
        ("Ski Sentrum", "Nordre Follo", ["Ski"], False),  # decided: the whole town, ±2 500 m
        ("Thon Senter Jessheim", "Ullensaker", ["Jessheim"], False),
        ("Osl", "Ullensaker", ["Oslo lufthavn"], False),
        ("Gardermoen Osl", "Ullensaker", ["Gardermoen Osl", "Gardermoen"], False),
        ("Jessheim- Henrik Bulls Veg", "Ullensaker",
         ["Henrik Bulls Veg", "Jessheim", "Henrik", "Bulls"], False),
        ("Sentrum", "Lillestrøm", [], True),
        ("Lillestrøm Sentrum", "Lillestrøm", [], True),
        ("Rv159 Retning E6", "Lørenskog", [], False),  # a road and a direction: nothing to look up
    ],
)  # fmt: skip
def test_area_candidates(area: str, kommune: str, kandidater: list[str], kommune_nevnt: bool) -> None:
    assert omrade_kandidater(omradedeler(area, kommune), kommune) == (kandidater, kommune_nevnt)


@pytest.mark.parametrize(
    "tekst, kommune, kandidater, kommune_nevnt",
    [
        ("melding om brann i bygning på Åkrene. Ukjent omfang.", "Lillestrøm", ["Åkrene"], False),
        ("kontroll ifm. skolestart ved Skogmo Skole.", "Ullensaker", ["Skogmo Skole", "Skogmo"], False),
        ("Kontrollerte en bil i nærheten av Gardermoen.", "Ullensaker", ["Gardermoen"], False),
        ("sist i området Hvalstad i dag tidlig", "Asker", ["Hvalstad"], False),
        ("av en Golden Retriever ved Lysdammen for en liten stund", "Gjerdrum", ["Lysdammen"], False),
        ("Politiet stanset en bil på E6 ved Vinterbro", "Ås", ["Vinterbro"], False),
        ("to personer som slåss i Lillestrøm. En person", "Lillestrøm", [], True),
        ("Politiet stanset et kjøretøy. Fører hadde ikke gyldig førerkort.", "Nes", [], False),
    ],
)  # fmt: skip
def test_text_candidates(tekst: str, kommune: str, kandidater: list[str], kommune_nevnt: bool) -> None:
    assert tekst_kandidater(tekst, kommune) == (kandidater, kommune_nevnt)


def sted(typ: str) -> dict:
    return {"lat": 60.0, "lon": 11.0, "usikkerhet_m": 150.0, "kilde": "stedsnavn", "detalj": typ}


@pytest.mark.parametrize(
    "res, kandidat, ok",
    [
        (sted("bru"), "Strand", False),  # «E18 ved Strand»: the bridge only shares the name
        (sted("bru"), "Olumsbrua", True),  # the name says it is the bridge
        (sted("holdeplass"), "Helsfyr", False),
        (sted("landskapsområde"), "Follo", False),  # a whole region
        (sted("tettsted"), "Kløfta", True),
        ({"lat": 60.0, "lon": 11.0, "usikkerhet_m": 314.0, "kilde": "gate", "detalj": "13 adresser"},
         "Henrik Bulls Veg", True),
    ],
)  # fmt: skip
def test_only_trustworthy_results_are_accepted(res: dict, kandidat: str, ok: bool) -> None:
    assert akseptabel(res, kandidat) is ok
