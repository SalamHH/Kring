"""Incident titles (spec §7.3, D5): category + place, from our own fields, never police text.

«Brann · Hølandsgata». The category is the app category (Appendix B); for Andre, which groups
several police categories, the police category itself («Ulykke · Lysaker»), since «Andre» says
nothing (decided 2026-11-14). The place is the matched street or place name, else the area field,
else the municipality; for a district-wide notice, the district.
"""

from __future__ import annotations

from app.match.categories import app_category

SEP = " · "


def district_name(district: str | None) -> str:
    """Politiloggen writes «Oslo Politidistrikt»; Norwegian writes «Oslo politidistrikt»."""
    d = " ".join((district or "").split())
    if d.lower().endswith(" politidistrikt"):
        d = d[: -len("politidistrikt")] + "politidistrikt"
    return d


def category_label(police_category: str) -> str:
    app = app_category(police_category)
    return police_category if app == "Andre" else app


def place_label(
    *,
    scope: str,
    geocode_method: str | None,
    geocode_match: str | None,
    area: str | None,
    municipality: str | None,
    district: str | None,
) -> str:
    if scope == "distrikt":
        return district_name(district or municipality)
    for candidate in (geocode_match if geocode_method not in (None, "kommune") else None, area, municipality):
        c = " ".join((candidate or "").split())
        if c:
            return c
    return district_name(district)


def title(
    *,
    category: str,
    scope: str = "kommune",
    geocode_method: str | None = None,
    geocode_match: str | None = None,
    area: str | None = None,
    municipality: str | None = None,
    district: str | None = None,
) -> str:
    place = place_label(
        scope=scope,
        geocode_method=geocode_method,
        geocode_match=geocode_match,
        area=area,
        municipality=municipality,
        district=district,
    )
    label = category_label(category)
    return f"{label}{SEP}{place}" if place else label
