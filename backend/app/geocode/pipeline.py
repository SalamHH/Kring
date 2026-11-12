"""Geocoding pipeline (spec §9.1): place one police-log event from its area field and text.

Async port of `Geokoder.sted/gate/adresse` and `plasser()` in research/presisjonstest.py (v4).
The order of steps, and the order of lookups within each step, follow the script exactly, so
recorded Kartverket responses replay and results can be compared with the script.

Order: exact address → crossing → street (area field, then text; long streets limited to the
area; downgraded to the area if still less precise) → area place name → municipality only.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.geocode.cache import CachedKartverket
from app.geocode.geometry import Point, begrens_til_omrade, kryss_mellom, oppsummer_punkter
from app.geocode.places import STED_ALIAS
from app.geocode.text import (
    finn_husnummer,
    finn_kryss,
    gatekandidater_fra_omrade,
    gatekandidater_fra_tekst,
    gatevarianter,
    norm,
    omradedeler,
)

LANG_GATE_M = 1000  # streets less precise than this are limited to the area (§9.1 step 4)
OMRADE_MIN_RADIUS_M = 800.0

# Script method labels → events.geocode_method (spec §8.4)
METHOD_NAMES = {
    "adresse": "adresse",
    "kryss": "kryss",
    "gate (area)": "gate_area",
    "gate (tekst)": "gate_tekst",
    "gate+område": "gate_omrade",
    "stedsnavn (area)": "stedsnavn",
    "kun kommune": "kommune",
}


@dataclass(frozen=True)
class Placement:
    """Where an event is, and how sure we are. lat/lon/uncertainty_m are None for «kommune»."""

    lat: float | None
    lon: float | None
    uncertainty_m: float | None  # unrounded; rounding happens when stored (§6.2)
    method: str  # one of METHOD_NAMES.values()
    match: str  # what was matched, e.g. "Trondheimsveien 33", "Mosseveien ved Ulvøya"
    detail: str  # e.g. Kartverket address text, place type, "99 adresser nær Rosenhoff"

    @property
    def has_point(self) -> bool:
        return self.lat is not None and self.lon is not None


def _placement(res: dict[str, Any], treff: str, metode: str) -> Placement:
    return Placement(
        lat=res.get("lat"),
        lon=res.get("lon"),
        uncertainty_m=res.get("usikkerhet_m"),
        method=METHOD_NAMES[metode],
        match=treff,
        detail=res.get("detalj") or "",
    )


class Geocoder:
    """Places events within one municipality (kommunenummer + name)."""

    def __init__(self, geo: CachedKartverket, knr: str, kommune: str) -> None:
        self.geo = geo
        self.knr = knr
        self.kommune = kommune

    # --- lookups (Geokoder in the script) ------------------------------------------------------

    async def gate_punkter(self, navn: str) -> tuple[str, list[Point]] | None:
        """All address points along a street: (spelling that matched, points)."""
        for v in gatevarianter(navn):
            pkt = await self.geo.adresse_punkter(v, self.knr)
            if pkt:
                return v, pkt
        return None

    async def gate(self, navn: str) -> dict[str, Any] | None:
        res = await self.gate_punkter(navn)
        if not res:
            return None
        return oppsummer_punkter(res[1], kilde="gate")

    async def adresse(self, gate: str, nummer: str, bokstav: str = "") -> dict[str, Any] | None:
        for v in gatevarianter(gate):
            res = await self.geo.adresse_eksakt(v, nummer, bokstav, self.knr)
            if res:
                return res
        return None

    async def sted(self, navn: str) -> dict[str, Any] | None:
        alias = STED_ALIAS.get((self.knr, norm(navn)))
        if alias:
            return dict(alias)
        res = await self.geo.stedsnavn(navn, self.knr)
        if res and res.get("detalj") == "adressenavn":  # §9.2: a street name, geocode as a street
            gate = await self.gate(navn)
            if gate:
                return gate
        return res

    # --- pipeline (plasser in the script) ------------------------------------------------------

    async def place(self, area: str | None, text: str | None) -> Placement:
        deler = omradedeler(area, self.kommune)
        tekst = text or ""

        # The area as a place name: fallback, and used to limit long streets.
        omrade_sted: dict[str, Any] | None = None
        for d in deler:
            res = await self.sted(d)
            if res and res.get("kilde") == "stedsnavn":
                omrade_sted = {**res, "treff": d}
                break

        # 1) Exact address (street + house number), area field first, then text
        for kilde_tekst, kandidater in (
            (area or "", gatekandidater_fra_omrade(deler)),
            (tekst, gatekandidater_fra_tekst(tekst)),
        ):
            for g in kandidater:
                nr = finn_husnummer(kilde_tekst, g)
                if nr:
                    res = await self.adresse(g, *nr)
                    if res:
                        return _placement(res, f"{g} {nr[0]}{nr[1]}", "adresse")

        # 2) Crossing between two streets
        for a, b in finn_kryss(f"{area or ''} . {tekst}"):
            pa = await self.gate_punkter(a)
            pb = await self.gate_punkter(b)
            if pa and pb:
                res = kryss_mellom(pa[1], pb[1])
                if res:
                    return _placement(res, f"{pa[0]} x {pb[0]}", "kryss")

        # 3) Street from the area field, then from the text
        for metode, kandidater in (
            ("gate (area)", gatekandidater_fra_omrade(deler)),
            ("gate (tekst)", gatekandidater_fra_tekst(tekst)),
        ):
            for g in kandidater:
                pkt = await self.gate_punkter(g)
                if not pkt:
                    continue
                navn, punkter = pkt
                res, treff = oppsummer_punkter(punkter, kilde="gate"), navn
                # 3b) Long street: use only the part near the area
                if res["usikkerhet_m"] > LANG_GATE_M and omrade_sted:
                    radius = max(omrade_sted["usikkerhet_m"], OMRADE_MIN_RADIUS_M)
                    begrenset = begrens_til_omrade(punkter, omrade_sted, radius)
                    if begrenset:
                        res, treff, metode = begrenset, f"{navn} ved {omrade_sted['treff']}", "gate+område"
                # 3c) Still less precise than the area? Then the area is better.
                if omrade_sted and res["usikkerhet_m"] > omrade_sted["usikkerhet_m"]:
                    return _placement(omrade_sted, omrade_sted["treff"], "stedsnavn (area)")
                return _placement(res, treff, metode)

        # 4) Place name from the area field
        if omrade_sted:
            return _placement(omrade_sted, omrade_sted["treff"], "stedsnavn (area)")

        # 5) Municipality only: no point, tier bydel, never pushed
        return Placement(None, None, None, "kommune", area or "", "")
