"""Event classification (spec §6.2, §9.3): planned controls, severity, precision tier."""

from __future__ import annotations

import math
import re
from typing import Literal

Severity = Literal["severe", "normal"]
Tier = Literal["gate", "nabolag", "bydel"]

# Planned traffic controls (§9.3). Verbatim from the reference script, which also accepts
# "trafikk-kontroll" (the script wins where it and the spec differ; decided 2026-11-12).
KONTROLL = re.compile(
    r"\b(trafikkontroll|trafikk-kontroll|fartskontroll|laserkontroll|hastighetskontroll|"
    r"ruskontroll|aksjon skolevei|trafikkorpset har avholdt)\w*",
    re.I,
)

# Severity heuristic v1 (§6.2). All keywords match as case-insensitive substrings
# (decided 2026-11-12).
SEVERE_CATEGORIES = frozenset({"Brann", "Voldshendelse", "Savnet", "Redning", "Ulykke"})
SEVERE_KEYWORDS = (
    "kniv", "skudd", "skyt", "våpen", "eksplosjon", "evakuer", "ran", "trusselsituasjon", "gissel",
)  # fmt: skip
SEVERE_TRAFFIC_KEYWORDS = ("alvorlig skadd", "omkommet", "påkjørt barn")

TIER_GATE_MAX_M = 500
TIER_NABOLAG_MAX_M = 1500


def is_control(category: str | None, text: str | None) -> bool:
    """Planned traffic control: category Trafikk and the text names a control."""
    return str(category) == "Trafikk" and bool(KONTROLL.search(text or ""))


def _contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    t = text.lower()
    return any(k in t for k in keywords)


def severity(category: str | None, text: str | None) -> Severity:
    """§6.2: severe by category, or by keyword in the text. Trafikk is severe only if the
    text contains one of the traffic keywords; the general keyword list does not apply to it."""
    text = text or ""
    if category == "Trafikk":
        return "severe" if _contains_any(text, SEVERE_TRAFFIC_KEYWORDS) else "normal"
    if category in SEVERE_CATEGORIES or _contains_any(text, SEVERE_KEYWORDS):
        return "severe"
    return "normal"


def round_uncertainty(u: float | None) -> int | None:
    """Round half-up to whole metres before storing (decided 2026-11-12)."""
    if u is None:
        return None
    return math.floor(u + 0.5)


def precision_tier(uncertainty_m: int | None) -> Tier:
    """§6.2, from the stored (already rounded) uncertainty: gate ≤ 500 < nabolag ≤ 1 500 < bydel.
    No point (None) is bydel."""
    if uncertainty_m is None or uncertainty_m > TIER_NABOLAG_MAX_M:
        return "bydel"
    if uncertainty_m > TIER_GATE_MAX_M:
        return "nabolag"
    return "gate"
