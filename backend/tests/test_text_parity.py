"""Parity: the ported text functions must return exactly what the reference script returns.

The oracle is research/presisjonstest.py, imported as a module (it needs `requests`, a dev
dependency). The corpus is hand-written police-log style text for now; recorded live thread
texts are added in M0 step 6 (tests/fixtures/politiloggen/).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

from app.classify.rules import is_control
from app.geocode import text as port
from app.geocode.geometry import haversine_m
from app.ingest.fields import pick

SCRIPT = Path(__file__).resolve().parents[2] / "research" / "presisjonstest.py"


def _load_oracle() -> ModuleType:
    spec = importlib.util.spec_from_file_location("presisjonstest", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["presisjonstest"] = module
    spec.loader.exec_module(module)
    return module


ref = _load_oracle()

TEXTS = [
    # Appendix C texts
    "Nødetatene er på vei til Trondheimsveien 33 etter melding om brann i 3 etasje",
    "Det har vært et sammenstøt mellom to biler i Trondheimsveien",
    "I krysset Louises gate/Ullevålsveien har det vært en trafikkulykke",
    "Bilen stoppet i avkjøringsrampen mot Maridalsveien",
    "Politiet opplyser at hendelsen er i Økern Torgvei 1",
    "Politiet har hatt trafikkontroll i Holtegata",
    "Holtegata hvor fartsgrensen er 30 km/t",
    "krysset Hausmannsgate/Storgata",
    "Ran av en person sør for Enebakkveien",
    # Other shapes the rules handle
    "Brann i Steenstrups gate 1b, røykutvikling fra 2. etasje",
    "Trafikkuhell Økernveien x Kjølberggata, ingen personskader",
    "Ulykke i krysset Nedre Prinsdalsvei og Høydalsveien",
    "Mann kjørte videre mot Ring 3 etter ulykken i Sinsenveien",
    "Gjerningspersonen løp mot Carl Berners plass",
    "Personen forsvant i retning Tøyengata",
    "Også Kong Oscars gate er stengt",
    "Melding om slagsmål på Youngstorget, 4 personer involvert",
    "Thorvald Meyers gate 40: innbrudd i leilighet",
    "Trafikkulykke på Mosseveien ved Ulvøya, 2 biler involvert",
    "Bil kjørt inn i Bygdøy allé 12",
    "Patrulje på stedet i Pilestredet 7 etter melding om bråk",
    "Brann i bygning i Kirkegaten 15, 4 etasje",
    "Avkjøringen til Tåsentunnelen er stengt",
    "Fartskontroll i Trondheimsveien, 12 forenklede forelegg",
    "Trafikkorpset har avholdt laserkontroll i Kirkeveien",
    "Aksjon skolevei ved Ruseløkka skole",
    "Ruskontroll på E18 ved Lysaker",
    "Person savnet fra Furuset, sist sett ved Furuset senter",
    "Politiet har sperret av Dronning Eufemias gate mellom Bjørvika og Oslo S",
    "Slagsmål utenfor Oslo City i Stenersgata 1",
    "Kollisjon mellom sykkel og bil i Ullevålsveien 64B",
    "Vi har kontroll på stedet i Åkebergveien",
    "Ingen gatenavn her, bare en melding om røyk",
    "",
    "Røyk fra bolig. Nødetatene på vei til Nordstrandveien 5 og 7",
    "Trafikkulykke i Sørkedalsveien hvor 3 biler er involvert",
    "Mann skadet med kniv i Grønlandsleiret 2 år etter forrige hendelse",
    "Brann i bil på Strømsveien x Tvetenveien",
    "Politiet kjørte til Kongsveien/Ekebergveien",
]

AREAS = [
    "Rosenhoff",
    "Tåsentunnelen",
    "Nedre Kalbakkvei",
    "Mosseveien V/ Ulvøya",
    "E6 Furuset",
    "Furuset",
    "Sentrum",
    "Bjørndal",
    "Grünerløkka, Oslo",
    "Rv. 4 Grorud - Kalbakken",
    "E18 Bygdøylokket",
    "Ring 3 Økern Østgående",
    "Majorstua; Frogner",
    "Bryn v. Brynsbakken",
    "Oslo",
    "Hosle ved Bærum",
    "Fv. 160 Vøyenenga",
    "",
    "None",
]

CATEGORIES = ["Trafikk", "Brann", "Ro og orden", "Ukjent"]


@pytest.mark.parametrize("text", TEXTS)
@pytest.mark.parametrize("med_filter", [False, True])
def test_finn_gatenavn(text: str, med_filter: bool) -> None:
    assert port.finn_gatenavn(text, med_filter) == ref.finn_gatenavn(text, med_filter)


@pytest.mark.parametrize("text", TEXTS + AREAS)
def test_finn_kryss(text: str) -> None:
    assert port.finn_kryss(text) == ref.finn_kryss(text)


@pytest.mark.parametrize("text", TEXTS)
def test_finn_husnummer(text: str) -> None:
    for gate in ref.finn_gatenavn(text):
        assert port.finn_husnummer(text, gate) == ref.finn_husnummer(text, gate), gate


@pytest.mark.parametrize("area", AREAS)
@pytest.mark.parametrize("kommune", ["Oslo", "Bærum"])
def test_omradedeler(area: str, kommune: str) -> None:
    assert port.omradedeler(area, kommune) == ref.omradedeler(area, kommune)


@pytest.mark.parametrize("text", TEXTS + AREAS)
def test_gatevarianter(text: str) -> None:
    for gate in ref.finn_gatenavn(text):
        assert port.gatevarianter(gate) == ref.Geokoder._gatevarianter(gate), gate


@pytest.mark.parametrize("text", TEXTS)
@pytest.mark.parametrize("category", CATEGORIES)
def test_is_control(text: str, category: str) -> None:
    assert is_control(category, text) == ref.er_kontroll({"kategori": category, "tekst": text})


@pytest.mark.parametrize("value", ["  Oslo  S ", "FURUSET", "", None, "Økern\ttorgvei"])
def test_norm(value: str | None) -> None:
    assert port.norm(value) == ref.norm(value)


def test_haversine() -> None:
    pairs = [(59.9133, 10.7389, 59.9110, 10.7522), (59.9, 10.7, 59.9, 10.7), (59.0, 10.0, 60.0, 11.0)]
    for p in pairs:
        assert haversine_m(*p) == ref.haversine_m(*p)


@pytest.mark.parametrize(
    "obj",
    [
        {"id": "a1", "Municipality": "Oslo"},
        {"ID": "a2", "municipality": {"name": "Bærum"}},
        {"threadId": "a3", "municipality": {"Navn": "Asker"}},
        {"id": "", "messageThreadId": "a4", "kommune": None, "municipalityName": "Lørenskog"},
        {"id": "a5", "municipality": {"code": "0301"}},
        {"municipality": []},
        "not a dict",
    ],
)
def test_pick(obj: object) -> None:
    for names in (ref.FELT_ID, ref.FELT_KOMMUNE):
        assert pick(obj, names) == ref.pick(obj, names)


def test_constants_match_script() -> None:
    """Regexes and word lists are copied verbatim; catch drift if the script changes."""
    assert port.VEIPREFIKS.pattern == ref.VEIPREFIKS.pattern
    assert port.GATE_SAMMENSATT.pattern == ref.GATE_SAMMENSATT.pattern
    assert port.GATE_SEPARAT.pattern == ref.GATE_SEPARAT.pattern
    assert port.RETNINGSKONTEKST.pattern == ref.RETNINGSKONTEKST.pattern
    assert port.KRYSS_SEP.pattern == ref.KRYSS_SEP.pattern
    assert port.STOPPORD == ref.STOPPORD
