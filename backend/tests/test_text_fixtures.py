"""Text-only parts of the Appendix C fixtures. The Kartverket-dependent parts (which
address/street/place the candidates resolve to) are tested in step 5 against recorded
responses. Assertions stay within what the Expected column states (decided 2026-11-12)."""

from __future__ import annotations

from app.classify.rules import is_control
from app.geocode.text import (
    finn_gatenavn,
    finn_husnummer,
    finn_kryss,
    gatekandidater_fra_omrade,
    gatekandidater_fra_tekst,
    gatevarianter,
    omradedeler,
)

OSLO = "Oslo"


def test_c01_house_number_not_floor() -> None:
    text = "Nødetatene er på vei til Trondheimsveien 33 etter melding om brann i 3 etasje"
    assert "Trondheimsveien" in gatekandidater_fra_tekst(text)
    assert finn_husnummer(text, "Trondheimsveien") == ("33", "")


def test_c02_street_from_text() -> None:
    text = "Det har vært et sammenstøt mellom to biler i Trondheimsveien"
    assert omradedeler("Rosenhoff", OSLO) == ["Rosenhoff"]
    assert gatekandidater_fra_tekst(text) == ["Trondheimsveien"]


def test_c03_crossing_slash() -> None:
    text = "I krysset Louises gate/Ullevålsveien har det vært en trafikkulykke"
    assert finn_kryss(text) == [("Louises gate", "Ullevålsveien")]


def test_c04_direction_filter_skips_maridalsveien() -> None:
    text = "Bilen stoppet i avkjøringsrampen mot Maridalsveien"
    assert "Maridalsveien" in finn_gatenavn(text)  # found without the filter ...
    assert "Maridalsveien" not in gatekandidater_fra_tekst(text)  # ... and removed by it


def test_c05_two_word_street_with_number() -> None:
    text = "Politiet opplyser at hendelsen er i Økern Torgvei 1"
    kandidater = gatekandidater_fra_tekst(text)
    assert kandidater[0] == "Økern Torgvei"
    assert finn_husnummer(text, "Økern Torgvei") == ("1", "")


def test_c06_area_whole_street_first() -> None:
    kandidater = gatekandidater_fra_omrade(omradedeler("Nedre Kalbakkvei", OSLO))
    assert kandidater[0] == "Nedre Kalbakkvei"


def test_c07_area_split_on_v_slash() -> None:
    assert omradedeler("Mosseveien V/ Ulvøya", OSLO) == ["Mosseveien", "Ulvøya"]


def test_c08_planned_control() -> None:
    text = "Politiet har hatt trafikkontroll i Holtegata"
    assert is_control("Trafikk", text) is True
    assert is_control("Ro og orden", text) is False


def test_c09_road_prefix_stripped() -> None:
    assert omradedeler("E6 Furuset", OSLO) == ["Furuset"]


def test_c12_speed_limit_is_not_a_house_number() -> None:
    assert finn_husnummer("Holtegata hvor fartsgrensen er 30 km/t", "Holtegata") is None
    # §9.1: a number directly after the street but followed by «km» is not a house number either
    assert finn_husnummer("Holtegata 30 km/t", "Holtegata") is None


def test_c13_crossing_with_spelling_variant() -> None:
    assert finn_kryss("krysset Hausmannsgate/Storgata") == [("Hausmannsgate", "Storgata")]
    assert "Hausmanns gate" in gatevarianter("Hausmannsgate")
    assert gatevarianter("Storgata")[0] == "Storgata"


def test_c14_text_street_not_direction() -> None:
    text = "Ran av en person sør for Enebakkveien"
    assert omradedeler("Bjørndal", OSLO) == ["Bjørndal"]
    assert gatekandidater_fra_omrade(["Bjørndal"]) == []
    assert gatekandidater_fra_tekst(text) == ["Enebakkveien"]


# Extra cases from §9.1-9.3 rules (not Appendix C fixtures)


def test_house_number_with_letter() -> None:
    assert finn_husnummer("Brann i Steenstrups gate 1b", "Steenstrups gate") == ("1", "b")


def test_crossing_x_and_krysset_og() -> None:
    assert finn_kryss("Trafikkuhell Økernveien x Kjølberggata") == [("Økernveien", "Kjølberggata")]
    assert finn_kryss("i krysset Nedre Prinsdalsvei og Høydalsveien") == [
        ("Nedre Prinsdalsvei", "Høydalsveien")
    ]


def test_area_drops_municipality_and_splits() -> None:
    assert omradedeler("Grünerløkka, Oslo", OSLO) == ["Grünerløkka"]
    assert omradedeler("Rv. 4 Grorud - Kalbakken", OSLO) == ["Grorud", "Kalbakken"]
    assert omradedeler(None, OSLO) == []


def test_stop_words_dropped() -> None:
    assert finn_gatenavn("Politiet Trondheimsveien") == ["Trondheimsveien"]


def test_known_limitation_capitalised_word_before_crossing() -> None:
    """Inherited from the reference script: a capitalised word that is not a stop-word
    («Ulykke») is taken as part of the first street name, and finn_kryss keeps only the
    longest candidate. Recorded so that changing it (e.g. adding stop-words) is deliberate."""
    assert finn_kryss("Ulykke Økernveien x Kjølberggata") == [("Ulykke Økernveien", "Kjølberggata")]


def test_gata_variants() -> None:
    assert gatevarianter("Holtegata") == ["Holtegata", "Holtegate"]
    assert gatevarianter("Kirkegaten") == ["Kirkegaten", "Kirkegate"]
