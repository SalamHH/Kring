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


def test_substring_match_is_decided_behaviour() -> None:
    """Case-insensitive substring matching (decided 2026-11-12) means «ran» also matches
    inside other words, e.g. «stranden». Recorded here so a change is deliberate."""
    assert severity("Ro og orden", "Bråk på stranden") == "severe"
