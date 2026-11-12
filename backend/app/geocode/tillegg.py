"""Additions to the reference geocoder for incidents it cannot place (spec §9.2).

Decided 2026-11-12 (Akershus pass). These run only where the script gives up and would store
the event at municipality level with no point. They never change a placement the script makes.

1. Area words the script can't look up (method «stedsnavn_utvidet»): direction words
   («E18 Inn Sandvika», «E6 Nordgående Kløfta», «Retning Oslo»), «Sentrum»/«Senter»
   («Ski Sentrum» → Ski, as the whole town), police shorthand («Osl» → Oslo lufthavn), and
   finally each capitalised word on its own («Gardermoen Osl», «Finstad Ski»). Each candidate
   is a normal place-name lookup in the municipality, with the normal radius for its type.
2. Place names in the message text when the area field is empty (method «stedsnavn_tekst»):
   only capitalised names right after «på», «ved», «i», «området», «nærheten av» and similar
   («brann i bygning på Åkrene», «ved Skogmo skole»).
3. The municipality's own name (method «kommunenavn»): «Sentrum» alone, the municipality name
   in the area field, or «i <municipality>» in the text. Placed at the town of the same name,
   only if the place-name register has it as a town («by» or «tettsted»), with that type's
   radius (2 500 m). Not for Oslo, where the town is the whole municipality.
"""

from __future__ import annotations

import re

from app.geocode.text import STOPPORD, norm

# Direction and lane words around a place in the area field.
_RETNING = re.compile(
    r"\b(?:inn|inng\.?|inngående|utg\.?|utgående|nordgående|sørgående|sydgående|østgående|"
    r"vestgående|retning\s+\S+|mot\s+\S+|kryss\s+\d+|sentrum|senter|thon)\b\.?",
    re.I,
)
_VEI = re.compile(r"^(?:E\s?\d+|Rv\.?\s?\d+|Fv\.?\s?\d+|Ring\s?\d)$", re.I)
SYNONYMER = {"osl": "Oslo lufthavn"}

# A capitalised place name (1 to 3 words, optionally followed by a facility word) after a
# place preposition.
_ORD = r"[A-ZÆØÅ][\wæøåÆØÅéü-]+"
_TEKSTSTED = re.compile(
    rf"\b(?:på|ved|i|området|nærheten\s+av|utenfor|nær)\s+"
    rf"({_ORD}(?:\s+{_ORD}){{0,2}}(?:\s+(?:skole|senter|stasjon|kirke|brygge|park))?)"
)
_IKKE_STED = STOPPORD | {"politiet", "politi", "ambulanse", "brannvesenet", "nødetatene", "amk"}

# Words that are never a place on their own.
_GENERISKE = frozenset({
    "nordre", "søndre", "øvre", "nedre", "store", "lille", "vestre", "østre", "ytre", "indre",
    "veg", "vei", "gate", "gata", "grensen", "skole", "stasjon", "togstasjon", "jernbanestasjon",
    "storsenter", "rett", "sør", "nord", "for",
})  # fmt: skip

KOMMUNE_TYPER = frozenset({"by", "tettsted"})

# A word on its own can hit a small object that only shares the name: «Helsfyr» the bus stop,
# «Strand» the bridge. Point-like types are only accepted when the name itself says so
# («Olumsbrua»). Region-sized types are never accepted: they would claim far too much.
_PUNKTTYPER = {"bru": ("bru", "brua", "broa", "brub"), "holdeplass": ("holdeplass",)}
_FOR_STORE = frozenset({"landskapsområde", "skogområde", "fjellområde", "annen administrativ inndeling"})


def akseptabel(res: dict, kandidat: str) -> bool:
    """Whether a lookup result for an added candidate is precise enough to trust."""
    typ = res.get("detalj") or ""
    if res.get("kilde") != "stedsnavn":
        return True  # a street (adressenavn → street geocoding) or an alias
    if typ in _FOR_STORE:
        return False
    endelser = _PUNKTTYPER.get(typ)
    return endelser is None or norm(kandidat).endswith(endelser)


UTEN_KOMMUNENAVN = frozenset({"0301"})  # Oslo: the town is the whole municipality


def _unik(seq: list[str]) -> list[str]:
    sett: set[str] = set()
    ut = []
    for s in seq:
        s = s.strip(" .,-")
        if s and norm(s) not in sett:
            sett.add(norm(s))
            ut.append(s)
    return ut


def omrade_kandidater(deler: list[str], kommune: str) -> tuple[list[str], bool]:
    """Place-name candidates from area-field parts the script could not place, and whether the
    area points at the municipality itself («Sentrum», «Lillestrøm Sentrum»)."""
    hele: list[str] = []  # whole cleaned parts first («Henrik Bulls Veg»)
    enkeltord: list[str] = []  # then single words («Gardermoen» from «Gardermoen Osl»)
    kommune_nevnt = False
    for d in [bit for del_ in deler for bit in re.split(r"(?<=\w)-\s+", del_)]:
        renset = re.sub(r"\s+", " ", _RETNING.sub(" ", d)).strip()
        ord_ = [o for o in renset.split() if not _VEI.match(o)]
        while ord_ and norm(ord_[0]) in _IKKE_STED:
            ord_ = ord_[1:]
        renset = " ".join(ord_)
        if not renset:
            # Only «Sentrum» on its own points at the municipality; «Rv159 Retning E6» does not.
            kommune_nevnt = kommune_nevnt or bool(re.search(r"\bsentrum\b", d, re.I))
            continue
        if norm(renset) == norm(kommune):
            kommune_nevnt = True
            continue
        hele.append(SYNONYMER.get(norm(renset), renset))
        if len(ord_) > 1:
            for o in ord_:
                if norm(o) == norm(kommune):
                    kommune_nevnt = True
                elif norm(o) not in _IKKE_STED | _GENERISKE and len(o) >= 4 and o[:1].isupper():
                    enkeltord.append(SYNONYMER.get(norm(o), o))
    hele.sort(key=lambda k: -len(k.split()))  # most specific first: a street before the town
    return _unik([k for k in hele + enkeltord if norm(k) != norm(kommune)]), kommune_nevnt


def tekst_kandidater(tekst: str, kommune: str) -> tuple[list[str], bool]:
    """Place-name candidates after a place preposition in the text, and whether the text says
    «i/på <municipality>»."""
    kand: list[str] = []
    kommune_nevnt = False
    for m in _TEKSTSTED.finditer(tekst or ""):
        navn = m.group(1)
        ord_ = navn.split()
        while ord_ and norm(ord_[0]) in _IKKE_STED:
            ord_ = ord_[1:]
        if not ord_:
            continue
        if _VEI.match(ord_[0]):
            continue  # «på E6 …» is a road, not a place
        navn = " ".join(ord_)
        if norm(navn) == norm(kommune) or norm(ord_[0]) == norm(kommune):
            kommune_nevnt = True
            continue
        kand.append(navn)
        if len(ord_) > 1:
            kand.append(ord_[0])  # «Skogmo skole» → also «Skogmo»
    return _unik(kand), kommune_nevnt
