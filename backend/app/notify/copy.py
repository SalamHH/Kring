"""Push copy (spec §7.4; D6). Built only from our own fields: no police text.

- Title: what + distance + place: «Brann ca. 150 m fra Hjemme».
- Body: where + status + precision: «Hølandsgata, Kampen. Brann, pågår. Presisjon: gate.»
- District Savnet (D2): «Savnet i Oslo politidistrikt» / «Politiet ber om tips. Trykk for å lese
  meldingen.»

Distances are rounded so they don't promise more than the placement can: to 50 m under 1 km
(at least «ca. 50 m»), else to 100 m, written «1,2 km» (decided 2026-11-14).
"""

from __future__ import annotations

from app.match.title import category_label, district_name, place_label


def distance_text(distance_m: float) -> str:
    if distance_m < 975:
        return f"{max(50, round(distance_m / 50) * 50)} m"
    km = round(distance_m / 100) / 10
    return f"{km:.1f}".replace(".", ",") + " km"


def push_title(*, category: str, distance_m: float, place_label_text: str) -> str:
    return f"{category_label(category)} ca. {distance_text(distance_m)} fra {place_label_text}"


def push_body(
    *,
    category: str,
    is_active: bool | None,
    precision_tier: str,
    geocode_method: str | None,
    geocode_match: str | None,
    area: str | None,
    municipality: str | None,
    district: str | None,
) -> str:
    where = place_label(
        scope="kommune",
        geocode_method=geocode_method,
        geocode_match=geocode_match,
        area=area,
        municipality=municipality,
        district=district,
    )
    area_text = " ".join((area or "").split())
    if area_text and area_text.lower() != where.lower():
        where = f"{where}, {area_text}"
    status = {True: "pågår", False: "avsluttet"}.get(is_active)  # type: ignore[call-overload]
    what = f"{category_label(category)}, {status}" if status else category_label(category)
    return f"{where}. {what}. Presisjon: {precision_tier}."


def district_title(*, category: str, district: str | None) -> str:
    return f"{category_label(category)} i {district_name(district)}"


DISTRICT_BODY = "Politiet ber om tips. Trykk for å lese meldingen."
