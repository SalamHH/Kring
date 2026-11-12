"""Classifier rules: precision tier, rounding, severity (spec §6.2)."""

from __future__ import annotations

import pytest

from app.classify.rules import precision_tier, round_uncertainty, severity


@pytest.mark.parametrize(
    ("u", "tier"),
    [
        (0, "gate"),
        (25, "gate"),
        (500, "gate"),
        (501, "nabolag"),
        (1000, "nabolag"),
        (1500, "nabolag"),
        (1501, "bydel"),
        (2500, "bydel"),
        (None, "bydel"),
    ],
)
def test_precision_tier_boundaries(u: int | None, tier: str) -> None:
    assert precision_tier(u) == tier


@pytest.mark.parametrize(
    ("raw", "rounded"),
    [(500.4, 500), (500.5, 501), (1500.49, 1500), (1500.5, 1501), (49.5, 50), (25.0, 25), (None, None)],
)
def test_round_half_up(raw: float | None, rounded: int | None) -> None:
    assert round_uncertainty(raw) == rounded


def test_tier_is_computed_from_rounded_value() -> None:
    assert precision_tier(round_uncertainty(500.4)) == "gate"
    assert precision_tier(round_uncertainty(500.5)) == "nabolag"


@pytest.mark.parametrize("category", ["Brann", "Voldshendelse", "Savnet", "Redning", "Ulykke"])
def test_severe_categories(category: str) -> None:
    assert severity(category, "Ingen detaljer") == "severe"


@pytest.mark.parametrize(
    ("category", "text", "expected"),
    [
        ("Tyveri", "Butikktyveri, gjerningsperson pågrepet", "normal"),
        ("Tyveri", "Mann truet ansatt med kniv", "severe"),
        ("Ro og orden", "Melding om SKUDD i området", "severe"),
        ("Andre hendelser", "Bygningen er evakuert", "severe"),
        ("Ro og orden", "Bråk i en leilighet", "normal"),
        ("Ukjent", "Ingen detaljer", "normal"),
        (None, None, "normal"),
    ],
)
def test_severity_by_keyword(category: str | None, text: str | None, expected: str) -> None:
    assert severity(category, text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Trafikkulykke, en person Alvorlig skadd", "severe"),
        ("En person omkommet etter ulykken", "severe"),
        ("Påkjørt barn ved skolen", "severe"),
        ("Mindre materielle skader", "normal"),
        # The general keyword list does not apply to Trafikk:
        ("Sjåføren hadde en kniv i bilen", "normal"),
    ],
)
def test_traffic_severity(text: str, expected: str) -> None:
    assert severity("Trafikk", text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "Mann ranet på åpen gate",
        "Ransforsøk mot butikk",
        "Melding om skyting",
        "Skuddveksling i området",
        "Knivstikking utenfor utested",
        "Huset er evakuert",
        "RAN av mobiltelefon",
        "Trusselsituasjon i leilighet",
    ],
)
def test_keyword_matches_at_word_start(text: str) -> None:
    assert severity("Ro og orden", text) == "severe"


@pytest.mark.parametrize(
    "text",
    [
        "Bråk på stranden",
        "Brannvesenet er varslet",
        "Transport av beruset person",
        "Personen var orangekledd",
    ],
)
def test_keyword_inside_word_does_not_match(text: str) -> None:
    """Word-start matching (decided 2026-11-12): «ran» inside «brannvesenet» etc. is not severe."""
    assert severity("Ro og orden", text) == "normal"


@pytest.mark.parametrize("text", ["Bankran i sentrum", "Melding om pistolskudd", "Gasseksplosjon i bolig"])
def test_known_limitation_keyword_at_end_of_compound(text: str) -> None:
    """Consequence of word-start matching: Norwegian compounds that end in a keyword
    («bankran», «pistolskudd», «gasseksplosjon») are not matched. Recorded so a change
    (e.g. a list of compounds) is deliberate; §6.2 says to tune severity in beta."""
    assert severity("Ro og orden", text) == "normal"


def test_traffic_phrase_at_word_start() -> None:
    assert severity("Trafikk", "Fotgjenger påkjørt barn?") == "severe"
    assert severity("Trafikk", "Ingen omkommet") == "severe"  # heuristic: no negation handling
