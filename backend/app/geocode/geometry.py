"""Geometry helpers. Ported from research/presisjonstest.py."""

from __future__ import annotations

import math
import statistics
from typing import Any

Point = list[float]  # [lat, lon]


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in metres (sphere, R = 6 371 km)."""
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def oppsummer_punkter(punkter: list[Point], kilde: str, detalj: str = "") -> dict[str, Any]:
    """Centroid + uncertainty: 90th-percentile distance from the centroid, at least 50 m (§9.1 step 3)."""
    clat = statistics.fmean(p[0] for p in punkter)
    clon = statistics.fmean(p[1] for p in punkter)
    avst = sorted(haversine_m(clat, clon, la, lo) for la, lo in punkter)
    p90 = avst[min(len(avst) - 1, int(0.9 * len(avst)))]
    return {
        "lat": clat,
        "lon": clon,
        "usikkerhet_m": max(50.0, p90),
        "kilde": kilde,
        "detalj": detalj or f"{len(punkter)} adresser",
    }


def kryss_mellom(a: list[Point], b: list[Point], maks_avstand_m: float = 250.0) -> dict[str, Any] | None:
    """Approximate crossing: the closest pair of address points on the two streets.
    Rejected if the streets never come closer than maks_avstand_m (§9.1 step 2)."""
    beste: tuple[float, float, float] | None = None
    for la1, lo1 in a:
        for la2, lo2 in b:
            # quick rough check before haversine (about 0.01° ≈ 1 km)
            if abs(la1 - la2) > 0.01 or abs(lo1 - lo2) > 0.02:
                continue
            d = haversine_m(la1, lo1, la2, lo2)
            if beste is None or d < beste[0]:
                beste = (d, (la1 + la2) / 2, (lo1 + lo2) / 2)
    if not beste or beste[0] > maks_avstand_m:
        return None
    d, lat, lon = beste
    return {
        "lat": lat,
        "lon": lon,
        "usikkerhet_m": max(75.0, d / 2 + 50),
        "kilde": "kryss",
        "detalj": f"nærmeste adresser {d:.0f} m fra hverandre",
    }


def begrens_til_omrade(punkter: list[Point], sted: dict[str, Any], radius_m: float) -> dict[str, Any] | None:
    """Use only the part of a long street near a known area (§9.1 step 4); needs ≥ 2 points."""
    naere = [p for p in punkter if haversine_m(sted["lat"], sted["lon"], p[0], p[1]) <= radius_m]
    if len(naere) < 2:
        return None
    return oppsummer_punkter(naere, kilde="gate+område", detalj=f"{len(naere)} adresser nær {sted['treff']}")
