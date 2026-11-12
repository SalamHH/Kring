"""Place-name selection from the Kartverket stedsnavn API (spec §9.2).

Tables and selection logic are ported verbatim from research/presisjonstest.py; where they
differ from the summary tables in §9.2, the script wins (decided 2026-11-12).

One deliberate deviation (decided 2026-11-12, after the M0 live run): the script gives every
type it doesn't list the same priority and then breaks the tie alphabetically, so a bridge
(«bru») named «Jessheim» beat the town («by») and was placed at ±150 m. The types in
TILLEGG_RADIUS / TILLEGG_PRIORITET are added to the script's tables. Tests compare against the
script with the same additions applied.
"""

from __future__ import annotations

from typing import Any

from app.geocode.text import norm

# Assumed uncertainty radius (metres) per navneobjekttype. Unknown types get STANDARD_STEDSRADIUS.
STEDSTYPE_RADIUS: dict[str, int] = {
    "bydel": 2500,
    "tettsted": 2500,
    "tettsteddel": 1200,
    "boligfelt": 500,
    "grend": 800,
    "gard": 700,  # in Oslo, farm names are often neighbourhoods (Sinsen, Torshov ...)
    "tettbebyggelse": 1000,
    "administrativ bydel": 2500,
    "industriområde": 600,
    "bruk": 300,
    "park": 400,
    "torg": 150,
    "holdeplass": 200,
    "stasjon": 300,
    "jernbanestasjon": 300,
    "t-banestasjon": 300,
    "skole": 200,
    "bru": 150,
    "vegkryss": 150,
    "kryss": 150,
    "senter": 300,
    "kjøpesenter": 300,
    "idrettsanlegg": 300,
    "øy": 1000,
    "nes": 800,
    "ås": 1000,
    "vann": 1000,
}
STANDARD_STEDSRADIUS = 1500

# Additions to the script's tables (see the module docstring). «by» ranks and sizes like
# «tettsted»; «flyplass» (Gardermoen) is an area as large as a town.
TILLEGG_RADIUS: dict[str, int] = {"by": 2500, "flyplass": 2500}
TILLEGG_PRIORITET: dict[str, int] = {"by": 14, "flyplass": 16}
STEDSTYPE_RADIUS.update(TILLEGG_RADIUS)

# When several objects share the name, prefer area types (lower = preferred). Bus stops and
# street names come last: «Furuset» in the police log means the area, not the bus stop.
STEDSTYPE_PRIORITET: dict[str, int] = {
    "administrativ bydel": 10, "bydel": 10, "tettbebyggelse": 11, "tettsteddel": 11,
    "boligfelt": 12, "grend": 13, "tettsted": 14, "strøk": 15, "nabolag": 15,
    "industriområde": 16, "senter": 20, "torg": 21, "park": 22, "gard": 25,
    "stasjon": 30, "jernbanestasjon": 30, "t-banestasjon": 30,
    "holdeplass": 90, "adressenavn": 95,
}  # fmt: skip
STEDSTYPE_PRIORITET.update(TILLEGG_PRIORITET)
UKJENT_PRIORITET = 50

# Police terms that are not official place names: (kommunenummer, normalised name) → placement.
# Sentrum / Oslo sentrum / Oslo S are from the script; Rosenhoff is decided 2026-11-12 (spec §9.2):
# the register has no area «Rosenhoff», so the point of «Rosenhoff skole» is used, with 800 m.
_OSLO_SENTRUM = {"lat": 59.9133, "lon": 10.7389, "usikkerhet_m": 1200.0,
                 "kilde": "stedsnavn", "detalj": "alias: Oslo sentrum"}  # fmt: skip
STED_ALIAS: dict[tuple[str, str], dict[str, Any]] = {
    ("0301", "sentrum"): _OSLO_SENTRUM,
    ("0301", "oslo sentrum"): _OSLO_SENTRUM,
    ("0301", "oslo s"): {"lat": 59.9110, "lon": 10.7522, "usikkerhet_m": 300.0,
                         "kilde": "stedsnavn", "detalj": "alias: Oslo S"},
    ("0301", "rosenhoff"): {"lat": 59.93098, "lon": 10.77447, "usikkerhet_m": 800.0,
                            "kilde": "stedsnavn", "detalj": "alias: Rosenhoff"},
}  # fmt: skip


def velg_stedsnavn(data: dict[str, Any], navn: str) -> dict[str, Any] | None:
    """Pick one place from a stedsnavn /navn response: exact spelling match on any
    skrivemåte, then the most area-like type. Returns the script's result shape
    {lat, lon, usikkerhet_m, kilde, detalj}, or None if nothing matches."""
    kandidater: list[tuple[int, str, float, float]] = []
    for item in data.get("navn", []):
        skrivemater = []
        if item.get("skrivemåte"):
            skrivemater.append(item["skrivemåte"])
        for s in item.get("stedsnavn") or []:
            if isinstance(s, dict) and s.get("skrivemåte"):
                skrivemater.append(s["skrivemåte"])
        if norm(navn) not in {norm(s) for s in skrivemater}:
            continue
        rp = item.get("representasjonspunkt") or {}
        lat = rp.get("nord", rp.get("lat"))
        lon = rp.get("øst", rp.get("ost", rp.get("lon")))
        if lat is None or lon is None:
            continue
        typ = norm(item.get("navneobjekttype"))
        kandidater.append((STEDSTYPE_PRIORITET.get(typ, UKJENT_PRIORITET), typ, float(lat), float(lon)))
    if not kandidater:
        return None
    _, typ, lat, lon = min(kandidater)
    radius = STEDSTYPE_RADIUS.get(typ, STANDARD_STEDSRADIUS)
    return {
        "lat": lat,
        "lon": lon,
        "usikkerhet_m": float(radius),
        "kilde": "stedsnavn",
        "detalj": typ or "ukjent type",
    }
