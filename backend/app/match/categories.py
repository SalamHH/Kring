"""App categories and their Politiloggen categories (spec Appendix B). The one place this
mapping lives (§8.5).

Places store app categories; events store police categories. Planned traffic controls are
excluded by `events.is_control`, not here.
"""

from __future__ import annotations

# In the order the app shows them.
APP_CATEGORIES: tuple[str, ...] = (
    "Vold",
    "Brann",
    "Savnet",
    "Ro og orden",
    "Innbrudd",
    "Tyveri",
    "Trafikk",
    "Andre",
)

POLICE_CATEGORIES: dict[str, tuple[str, ...]] = {
    "Vold": ("Voldshendelse",),
    "Brann": ("Brann",),
    "Savnet": ("Savnet",),
    "Ro og orden": ("Ro og orden",),
    "Innbrudd": ("Innbrudd",),
    "Tyveri": ("Tyveri",),
    "Trafikk": ("Trafikk",),
    "Andre": ("Ulykke", "Redning", "Skadeverk", "Sjø", "Dyr", "Vær", "Arrangement", "Andre hendelser"),
}


def canonical(categories: list[str]) -> list[str]:
    """Deduplicated, in APP_CATEGORIES order. Raises ValueError for an unknown category."""
    unknown = [c for c in categories if c not in POLICE_CATEGORIES]
    if unknown:
        raise ValueError(f"unknown categories: {', '.join(unknown)}")
    return [c for c in APP_CATEGORIES if c in categories]
