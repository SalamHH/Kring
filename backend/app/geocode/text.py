"""Text parsing for geocoding (spec §9.2, §9.3).

Ported from research/presisjonstest.py (v4); the script is the source of truth where it
and the spec disagree (decided 2026-11-12). Regexes and word lists are kept verbatim so
tests/test_text_parity.py can check this module against the script function by function.
"""

from __future__ import annotations

import re

# Road number in front of a place name, e.g. "E6 Furuset", "Rv. 4 Grorud", "Ring 3 Ulven"
VEIPREFIKS = re.compile(r"^(?:E\s?\d+|Rv\.?\s?\d+|Fv\.?\s?\d+|Ring\s?\d)\s*[,-]?\s*", re.I)

# Street names in free text: joined ("Trondheimsveien") or two words ("Thorvald Meyers gate")
GATE_SAMMENSATT = re.compile(
    r"\b[A-ZÆØÅ][a-zæøåéü]+(?:veien|vegen|veg|vei|gata|gaten|gate|plassen|torget|"
    r"bakken|stien|bryggen|kaia|ringen|svingen|tunnelen|alléen|alleen|hellinga)\b"
)
GATE_SEPARAT = re.compile(
    r"\b((?:[A-ZÆØÅ][\wæøåÆØÅéü\.]*\s){1,3})(gate|gata|vei|veg|plass|torg|allé|alle|bakke|brygge|kai)\b"
)

# Capitalised words that are not part of a street name (sentence starts etc.)
STOPPORD = {
    "i", "på", "ved", "mot", "fra", "til", "vi", "det", "der", "da", "politiet", "politi",
    "nødetatene", "patrulje", "patruljer", "brann", "og", "en", "et", "også", "nedenfor",
    "ovenfor", "krysset", "mellom", "etter", "melding", "trafikkulykke", "trafikkuhell",
}  # fmt: skip

# Street mentioned as a direction or exit, not as the incident location
RETNINGSKONTEKST = re.compile(
    r"(?:\bmot|\bretning|\bavkjøring\w*(?:\s+(?:mot|til))?|\bkjørte\s+(?:videre\s+)?(?:mot|til)|"
    r"\bløp\s+(?:mot|til)|\bforsvant\s+(?:mot|i\s+retning))\s*$",
    re.I,
)

KRYSS_SEP = re.compile(r"\s*(?:/|\s[xX]\s|\s+og\s+)\s*")

# Area-field parts that look like a whole street name
_OMRADE_GATESUFFIKS = re.compile(r"(vei|veg|gate|gata|plass|torg|allé|bakken|stien)$", re.I)


def norm(s: str | None) -> str:
    """Collapse whitespace, trim, lower-case. Used for cache keys and name comparison."""
    return re.sub(r"\s+", " ", (s or "").strip()).lower()


def gatevarianter(navn: str) -> list[str]:
    """Spelling variants to try against the address register: «-gata/-gaten» → «-gate»,
    «Hausmannsgate» → «Hausmanns gate». The original spelling comes first."""
    varianter = [navn]
    if navn.endswith("gaten"):
        varianter.append(navn[:-5] + "gate")
    if navn.endswith("gata"):
        varianter.append(navn[:-4] + "gate")
    m = re.match(r"^(.*[a-zæøå]s)(gate|gata)$", navn)
    if m and " " not in navn:
        varianter.append(m.group(1) + " gate")
    return varianter


def finn_gatenavn(tekst: str | None, med_kontekstfilter: bool = False) -> list[str]:
    """Street-name candidates in free text, longest variant first.
    'Økern Torgvei' gives ['Økern Torgvei', 'Torgvei']; leading stop-words are dropped.
    With med_kontekstfilter, streets named as a direction («… mot Maridalsveien») are skipped."""
    tekst = tekst or ""
    funn: list[str] = []

    def legg_til(ordliste: list[str], start: int) -> None:
        if med_kontekstfilter and RETNINGSKONTEKST.search(tekst[max(0, start - 40) : start]):
            return
        while ordliste and ordliste[0].lower().strip(".") in STOPPORD:
            ordliste = ordliste[1:]
        for i in range(len(ordliste)):
            funn.append(" ".join(ordliste[i:]))

    for m in GATE_SAMMENSATT.finditer(tekst):
        # up to two capitalised words right before ("Nedre Kalbakkvei", "Økern Torgvei")
        foran = re.search(r"((?:[A-ZÆØÅ][\wæøåéü\.]*\s){0,2})$", tekst[: m.start()])
        ord_ = (foran.group(1).split() if foran else []) + [m.group(0)]
        legg_til(ord_, m.start() - (len(foran.group(1)) if foran else 0))
    for m in GATE_SEPARAT.finditer(tekst):
        legg_til([*m.group(1).split(), m.group(2)], m.start())

    sett: set[str] = set()
    ut: list[str] = []
    for f in funn:
        if norm(f) not in sett and len(f) > 3 and f[0].isupper():
            sett.add(norm(f))
            ut.append(f)
    return ut


def finn_husnummer(tekst: str | None, gate: str) -> tuple[str, str] | None:
    """'Trondheimsveien 33' → ('33', ''), 'Steenstrups gate 1b' → ('1', 'b').
    Numbers followed by etasje, km, kmt, personer, biler or år are ignored."""
    m = re.search(
        re.escape(gate) + r"\s+(\d{1,4})\s?([A-Za-z])?(?![\w])(?!\s*(?:etasje|km|kmt|personer|biler|år))",
        tekst or "",
        re.I,
    )
    if not m:
        return None
    return m.group(1), (m.group(2) or "")


def finn_kryss(tekst: str | None) -> list[tuple[str, str]]:
    """Street pairs named as a crossing: 'Louises gate/Ullevålsveien',
    'Økernveien x Kjølberggata', 'krysset Nedre Prinsdalsvei og Høydalsveien'."""
    par: list[tuple[str, str]] = []
    tekst = tekst or ""
    # one street name: up to three capitalised words + a last word; does not cross a full stop
    navn = r"(?:[A-ZÆØÅ][\wæøåéü]*\s){0,3}[A-ZÆØÅ]?[\wæøåéü]+"
    for m in re.finditer(rf"({navn})(?:\s*/\s*|\s[xX]\s)({navn})", tekst):
        par.append((m.group(1), m.group(2)))
    for m in re.finditer(rf"[Kk]rysset\s+({navn})\s+og\s+({navn})", tekst):
        par.append((m.group(1), m.group(2)))
    ut: list[tuple[str, str]] = []
    for a, b in par:
        ga, gb = finn_gatenavn(a), finn_gatenavn(b)
        if ga and gb:
            ut.append((ga[0], gb[0]))
    return ut


def omradedeler(omrade: str | None, kommune: str) -> list[str]:
    """Split the area field ('Grünerløkka, Oslo', 'Mosseveien V/ Ulvøya'), strip road
    prefixes ('E6 Furuset' → 'Furuset') and drop the municipality name itself."""
    if not omrade or str(omrade) == "None":
        return []
    tekst = re.sub(r"\s+[Vv](?:/|\.|ed)\s*", ", ", str(omrade))
    deler = [d.strip(" .") for d in re.split(r"[,/;]| - ", tekst) if d.strip(" .")]
    ut: list[str] = []
    for d in deler:
        uten_vei = VEIPREFIKS.sub("", d).strip()
        if uten_vei and uten_vei != d:
            ut.append(uten_vei)
        elif uten_vei:
            ut.append(d)
    return [d for d in ut if norm(d) != norm(kommune)]


def gatekandidater_fra_omrade(deler: list[str]) -> list[str]:
    """Street candidates from area-field parts: a whole part that ends like a street name
    first ('Nedre Kalbakkvei'), then candidates found inside it."""
    ut: list[str] = []
    for d in deler:
        kand = [d] if _OMRADE_GATESUFFIKS.search(d) else []
        ut.extend(kand + [g for g in finn_gatenavn(d) if g not in kand])
    return ut


def gatekandidater_fra_tekst(tekst: str | None) -> list[str]:
    """Street candidates from message text, with the direction filter (§9.3)."""
    return finn_gatenavn(tekst, med_kontekstfilter=True)
