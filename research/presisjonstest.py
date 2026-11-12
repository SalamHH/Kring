#!/usr/bin/env python3
"""
Presisjonstest for Politiloggen
===============================

Spørsmål: Hvor stor andel av politiloggmeldingene i en kommune kan plasseres
presist nok til å si "dette skjedde innenfor X meter fra et sted"?

Hva skriptet gjør
  1. Henter meldingstråder fra Politiloggen-API-et (åpent, NLOD 2.0) og
     cacher dem lokalt.
  2. Filtrerer på kommune (standard: Oslo).
  3. Prøver å plassere hver hendelse, i denne rekkefølgen (versjon 4):
       a) gate + husnummer ("Trondheimsveien 33")   -> eksakt adresse
       b) kryss ("Louises gate/Ullevålsveien")      -> nærmeste punkt mellom gatene
       c) gatenavn i `area`, så i meldingsteksten   -> adresse-API; lange gater begrenses
          til delen nær stedsnavnet i `area`, og er gaten fortsatt upresis brukes området
       d) stedsnavnet i `area`                      -> stedsnavn-API
       e) bare kommune                              -> upresis
     Planlagte trafikkontroller merkes og holdes utenfor tallene.
  4. Anslår en usikkerhetsradius per hendelse:
       - gate:      90-persentil avstand fra gatens midtpunkt til adressene
                    langs gaten (lange gater = stor usikkerhet)
       - stedsnavn: antatt radius per navneobjekttype (se STEDSTYPE_RADIUS,
                    juster etter behov)
       - kommune:   ikke plasserbar
  5. Skriver resultat.csv (én rad per hendelse, for stikkprøver) og
     oppsummering.md, og skriver oppsummeringen til terminalen.

Bruk
  pip install requests
  python presisjonstest.py --sample           # se én rå tråd fra API-et først
  python presisjonstest.py                    # Oslo, siste kvartal
  python presisjonstest.py --kommune Bærum --kommunenummer 3201
  python presisjonstest.py --refresh          # hent politiloggen på nytt

Kartverket-API-ene som brukes (åpne, ingen nøkkel):
  https://ws.geonorge.no/adresser/v1/sok
  https://ws.geonorge.no/stedsnavn/v1/navn

Merk: Politiloggen-API-et er ikke stabilt dokumentert. Feltnavn hentes
defensivt (se `pick`). Kjør --sample først og juster FELT-konstantene om
noe ikke treffer.
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import math
import random
import re
import statistics
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

try:
    import requests
except ImportError:  # pragma: no cover
    sys.exit("Mangler 'requests'. Kjør: pip install requests")

POLITILOGG_URL = "https://api.politiloggen.politiet.no/messagethreads"
ADRESSE_URL = "https://ws.geonorge.no/adresser/v1/sok"
# Prøves i rekkefølge. Kommunefilteret heter `knr` i stedsnavn-API-et (ikke `kommunenummer`).
STEDSNAVN_URLER = [
    "https://ws.geonorge.no/stedsnavn/v1/navn",
    "https://api.kartverket.no/stedsnavn/v1/navn",
]

DATA_DIR = Path("presisjonsdata")
THREADS_FILE = DATA_DIR / "threads.json"
GEOCACHE_FILE = DATA_DIR / "geocache.json"

TERSKLER_M = [300, 500, 1000, 2000]

# Kandidat-feltnavn i Politiloggen-svaret (sjekkes uten hensyn til store/små bokstaver)
FELT_ID = ("id", "threadId", "messageThreadId")
FELT_KOMMUNE = ("municipality", "municipalityName", "kommune")
FELT_OMRADE = ("area", "areaName", "place", "location")
FELT_DISTRIKT = ("district", "districtName", "policeDistrict")
FELT_KATEGORI = ("category", "categoryName", "type")
FELT_MELDINGER = ("messages", "updates", "messageList")
FELT_TEKST = ("text", "message", "body", "content")
FELT_TID = ("createdOn", "createdAt", "startedOn", "firstMessageOn", "lastMessageOn")

# Antatt usikkerhetsradius (meter) per navneobjekttype i stedsnavn-API-et.
# Ukjente typer får STANDARD_STEDSRADIUS. Skriptet lister typene det møter,
# så du kan finjustere.
STEDSTYPE_RADIUS = {
    "bydel": 2500,
    "tettsted": 2500,
    "tettsteddel": 1200,
    "boligfelt": 500,
    "grend": 800,
    "gard": 700,          # i Oslo er gårdsnavn ofte nabolag (Sinsen, Torshov ...)
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

# Når samme navn finnes som flere objekttyper, foretrekk områdetyper (lavere tall = foretrekkes)
# Holdeplasser og adressenavn kommer sist: "Furuset" i politiloggen betyr området, ikke busstoppet.
STEDSTYPE_PRIORITET = {
    "administrativ bydel": 10, "bydel": 10, "tettbebyggelse": 11, "tettsteddel": 11,
    "boligfelt": 12, "grend": 13, "tettsted": 14, "strøk": 15, "nabolag": 15,
    "industriområde": 16, "senter": 20, "torg": 21, "park": 22, "gard": 25,
    "stasjon": 30, "jernbanestasjon": 30, "t-banestasjon": 30,
    "holdeplass": 90, "adressenavn": 95,
}

# Politiets egne betegnelser som ikke er offisielle stedsnavn. (kommunenummer, navn) -> plassering
_OSLO_SENTRUM = {"lat": 59.9133, "lon": 10.7389, "usikkerhet_m": 1200.0,
                 "kilde": "stedsnavn", "detalj": "alias: Oslo sentrum"}
STED_ALIAS = {
    ("0301", "sentrum"): _OSLO_SENTRUM,
    ("0301", "oslo sentrum"): _OSLO_SENTRUM,
    ("0301", "oslo s"): {"lat": 59.9110, "lon": 10.7522, "usikkerhet_m": 300.0,
                         "kilde": "stedsnavn", "detalj": "alias: Oslo S"},
}

class OppslagFeilet(Exception):
    """Nettverks-/API-feil. Lagres ikke i cachen, så oppslaget prøves igjen neste kjøring."""

# Veinummer foran stedsnavn, f.eks. "E6 Furuset", "Rv. 4 Grorud", "Ring 3 Ulven"
VEIPREFIKS = re.compile(r"^(?:E\s?\d+|Rv\.?\s?\d+|Fv\.?\s?\d+|Ring\s?\d)\s*[,-]?\s*", re.I)

# Gatenavn i fritekst: sammensatt ("Trondheimsveien") eller to ord ("Thorvald Meyers gate")
GATE_SAMMENSATT = re.compile(
    r"\b[A-ZÆØÅ][a-zæøåéü]+(?:veien|vegen|veg|vei|gata|gaten|gate|plassen|torget|"
    r"bakken|stien|bryggen|kaia|ringen|svingen|tunnelen|alléen|alleen|hellinga)\b"
)
GATE_SEPARAT = re.compile(
    r"\b((?:[A-ZÆØÅ][\wæøåÆØÅéü\.]*\s){1,3})(gate|gata|vei|veg|plass|torg|allé|alle|bakke|brygge|kai)\b"
)

HTTP = requests.Session()
HTTP.headers.update({"Accept": "application/json", "User-Agent": "presisjonstest/1.0 (privat analyse)"})


# --------------------------------------------------------------------------- hjelpere

def pick(obj: dict, names: tuple[str, ...]):
    """Hent første ikke-tomme felt blant kandidatnavn, uten hensyn til store/små bokstaver.
    Hvis verdien er et objekt, prøv name/value/displayName inni."""
    if not isinstance(obj, dict):
        return None
    lower = {k.lower(): v for k, v in obj.items()}
    for n in names:
        v = lower.get(n.lower())
        if v in (None, "", [], {}):
            continue
        if isinstance(v, dict):
            inner = pick(v, ("name", "value", "displayName", "navn"))
            if inner is not None:
                return inner
        return v
    return None


def norm(s: str | None) -> str:
    return re.sub(r"\s+", " ", (s or "").strip()).lower()


def haversine_m(lat1, lon1, lat2, lon2) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def get_json(url: str, params: dict, tries: int = 5) -> dict:
    delay = 1.0
    for _ in range(tries):
        resp = HTTP.get(url, params=params, timeout=30)
        if resp.status_code == 429 or resp.status_code >= 500:
            time.sleep(delay)
            delay *= 2
            continue
        resp.raise_for_status()
        return resp.json()
    resp.raise_for_status()
    return {}


# --------------------------------------------------------------------------- politiloggen

def hent_trader(timespan: str, page_size: int, max_threads: int | None) -> list[dict]:
    trader, skip = [], 0
    while True:
        data = get_json(POLITILOGG_URL, {
            "take": page_size,
            "skip": skip,
            "sortByEnum": "LastMessageOn",
            "timeSpanType": timespan,
        })
        side = data.get("messageThreads") or data.get("MessageThreads") or []
        trader.extend(side)
        print(f"  hentet {len(trader)} tråder ...", end="\r", flush=True)
        if not side or not data.get("hasMoreResults", False):
            break
        if max_threads and len(trader) >= max_threads:
            break
        skip += len(side)
        time.sleep(0.2)
    print()
    # dedupliser på id
    sett, unike = set(), []
    for t in trader:
        tid = pick(t, FELT_ID) or json.dumps(t, sort_keys=True)[:200]
        if tid in sett:
            continue
        sett.add(tid)
        unike.append(t)
    return unike


def trad_til_rad(t: dict) -> dict:
    meldinger = pick(t, FELT_MELDINGER) or []
    if not isinstance(meldinger, list):
        meldinger = []
    tekster = [str(pick(m, FELT_TEKST) or "") for m in meldinger if isinstance(m, dict)]
    tid = pick(t, FELT_TID)
    if not tid and meldinger and isinstance(meldinger[0], dict):
        tid = pick(meldinger[0], FELT_TID)
    return {
        "id": pick(t, FELT_ID),
        "kommune": pick(t, FELT_KOMMUNE),
        "omrade": pick(t, FELT_OMRADE),
        "distrikt": pick(t, FELT_DISTRIKT),
        "kategori": pick(t, FELT_KATEGORI) or "Ukjent",
        "tid": tid,
        "tekst": " ".join(tekster).strip(),
    }


# --------------------------------------------------------------------------- geometri

def oppsummer_punkter(punkter: list, kilde: str, detalj: str = "") -> dict:
    """Midtpunkt + usikkerhet (90-persentil avstand fra midtpunktet, minst 50 m)."""
    clat = statistics.fmean(p[0] for p in punkter)
    clon = statistics.fmean(p[1] for p in punkter)
    avst = sorted(haversine_m(clat, clon, la, lo) for la, lo in punkter)
    p90 = avst[min(len(avst) - 1, int(0.9 * len(avst)))]
    return {"lat": clat, "lon": clon, "usikkerhet_m": max(50.0, p90), "kilde": kilde,
            "detalj": detalj or f"{len(punkter)} adresser"}


def kryss_mellom(a: list, b: list, maks_avstand_m: float = 250.0) -> dict | None:
    """Tilnærmet kryss: de to nærmeste adressepunktene på hver sin gate.
    Avvises hvis gatene ikke kommer nærmere hverandre enn maks_avstand_m."""
    beste = None
    for la1, lo1 in a:
        for la2, lo2 in b:
            # rask grovsjekk før haversine (ca. 0,01 grad ≈ 1 km)
            if abs(la1 - la2) > 0.01 or abs(lo1 - lo2) > 0.02:
                continue
            d = haversine_m(la1, lo1, la2, lo2)
            if beste is None or d < beste[0]:
                beste = (d, (la1 + la2) / 2, (lo1 + lo2) / 2)
    if not beste or beste[0] > maks_avstand_m:
        return None
    d, lat, lon = beste
    return {"lat": lat, "lon": lon, "usikkerhet_m": max(75.0, d / 2 + 50), "kilde": "kryss",
            "detalj": f"nærmeste adresser {d:.0f} m fra hverandre"}


def begrens_til_omrade(punkter: list, sted: dict, radius_m: float) -> dict | None:
    """Bruk bare den delen av en lang gate som ligger nær et kjent område."""
    naere = [p for p in punkter if haversine_m(sted["lat"], sted["lon"], p[0], p[1]) <= radius_m]
    if len(naere) < 2:
        return None
    return oppsummer_punkter(naere, kilde="gate+område", detalj=f"{len(naere)} adresser nær {sted['treff']}")


# --------------------------------------------------------------------------- geokoding

class Geokoder:
    def __init__(self, kommunenummer: str):
        self.knr = kommunenummer
        self.cache: dict = json.loads(GEOCACHE_FILE.read_text("utf-8")) if GEOCACHE_FILE.exists() else {}
        self.kall = 0
        self.stedsfeil_vist = False
        self.feilede = 0

    def lagre(self):
        GEOCACHE_FILE.write_text(json.dumps(self.cache, ensure_ascii=False), "utf-8")

    def _cached(self, key, fn):
        if key not in self.cache:
            time.sleep(0.15)
            try:
                verdi = fn()
            except OppslagFeilet:
                self.feilede += 1
                return None  # ikke lagre – prøv igjen neste gang
            self.cache[key] = verdi
            self.kall += 1
            if self.kall % 25 == 0:
                self.lagre()
        return self.cache[key]

    @staticmethod
    def _gatevarianter(navn: str) -> list[str]:
        varianter = [navn]
        if navn.endswith("gaten"):
            varianter.append(navn[:-5] + "gate")
        if navn.endswith("gata"):
            varianter.append(navn[:-4] + "gate")
        # "Hausmannsgate" -> "Hausmanns gate"
        m = re.match(r"^(.*[a-zæøå]s)(gate|gata)$", navn)
        if m and " " not in navn:
            varianter.append(m.group(1) + " gate")
        return varianter

    def gate_punkter(self, navn: str) -> tuple[str, list] | None:
        """Alle adressepunkter langs en gate: (offisielt navn brukt, [(lat, lon), ...])."""
        for v in self._gatevarianter(navn):
            pkt = self._cached(f"adrp|{self.knr}|{norm(v)}", lambda v=v: self._adresse_punkter(v))
            if pkt:
                return v, pkt
        return None

    def gate(self, navn: str) -> dict | None:
        """Slå opp et gatenavn. Returnerer midtpunkt og usikkerhet (p90-avstand)."""
        res = self.gate_punkter(navn)
        if not res:
            return None
        _, punkter = res
        return oppsummer_punkter(punkter, kilde="gate")

    def _adresse_punkter(self, navn: str) -> list | None:
        try:
            data = get_json(ADRESSE_URL, {
                "adressenavn": navn,
                "kommunenummer": self.knr,
                "treffPerSide": 1000,
                "utkoordsys": 4258,
            })
        except (requests.HTTPError, requests.ConnectionError, requests.Timeout) as e:
            if getattr(getattr(e, "response", None), "status_code", None) in (400, 404):
                return None  # ugyldig/ukjent navn: et ekte "ikke funnet"
            raise OppslagFeilet(navn)
        punkter = []
        for a in data.get("adresser", []):
            rp = a.get("representasjonspunkt") or {}
            lat, lon = rp.get("lat"), rp.get("lon")
            if lat is not None and lon is not None:
                punkter.append([round(float(lat), 6), round(float(lon), 6)])
        return punkter or None

    def adresse(self, gate: str, nummer: str, bokstav: str = "") -> dict | None:
        """Eksakt adresse, f.eks. Trondheimsveien 33 eller Steenstrups gate 1b."""
        for v in self._gatevarianter(gate):
            key = f"adrn|{self.knr}|{norm(v)}|{nummer}{bokstav.lower()}"
            res = self._cached(key, lambda v=v: self._adresse_eksakt(v, nummer, bokstav))
            if res:
                return res
        return None

    def _adresse_eksakt(self, gate: str, nummer: str, bokstav: str) -> dict | None:
        params = {"adressenavn": gate, "nummer": nummer, "kommunenummer": self.knr,
                  "treffPerSide": 10, "utkoordsys": 4258}
        if bokstav:
            params["bokstav"] = bokstav.upper()
        try:
            data = get_json(ADRESSE_URL, params)
        except (requests.HTTPError, requests.ConnectionError, requests.Timeout) as e:
            if getattr(getattr(e, "response", None), "status_code", None) in (400, 404):
                return None
            raise OppslagFeilet(f"{gate} {nummer}")
        for a in data.get("adresser", []):
            rp = a.get("representasjonspunkt") or {}
            if rp.get("lat") is not None:
                return {"lat": float(rp["lat"]), "lon": float(rp["lon"]), "usikkerhet_m": 25.0,
                        "kilde": "adresse", "detalj": a.get("adressetekst") or f"{gate} {nummer}"}
        return None

    def sted(self, navn: str) -> dict | None:
        alias = STED_ALIAS.get((self.knr, norm(navn)))
        if alias:
            return dict(alias)
        # "sted2" i nøkkelen: ugyldiggjør feilslåtte oppslag fra første versjon av skriptet
        # "sted3": ugyldiggjør oppslag lagret av tidligere versjoner av skriptet
        res = self._cached(f"sted3|{self.knr}|{norm(navn)}", lambda: self._stedsnavn_sok(navn))
        if res and res.get("detalj") == "adressenavn":
            gate = self.gate(navn)
            if gate:
                return gate
        return res

    def _stedsnavn_sok(self, navn: str) -> dict | None:
        data = None
        for url in STEDSNAVN_URLER:
            try:
                data = get_json(url, {
                    "sok": navn,
                    "knr": self.knr,
                    "utkoordsys": 4258,
                    "treffPerSide": 25,
                    "fuzzy": "false",
                })
                break
            except (requests.HTTPError, requests.ConnectionError, requests.Timeout) as e:
                if not self.stedsfeil_vist:
                    kode = getattr(getattr(e, "response", None), "status_code", "nettverksfeil")
                    print(f"\n  [stedsnavn] {url} feilet ({kode}) – prøver igjen neste kjøring")
                    self.stedsfeil_vist = True
        if data is None:
            raise OppslagFeilet(navn)

        kandidater = []
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
            kandidater.append((STEDSTYPE_PRIORITET.get(typ, 50), typ, float(lat), float(lon)))
        if not kandidater:
            return None
        # Flere treff med samme navn (f.eks. både bydel og bussholdeplass): velg områdetypen
        _, typ, lat, lon = min(kandidater)
        radius = STEDSTYPE_RADIUS.get(typ, STANDARD_STEDSRADIUS)
        return {"lat": lat, "lon": lon, "usikkerhet_m": float(radius),
                "kilde": "stedsnavn", "detalj": typ or "ukjent type"}


# Store forbokstaver som ikke er del av et gatenavn (setningsstart o.l.)
STOPPORD = {"i", "på", "ved", "mot", "fra", "til", "vi", "det", "der", "da", "politiet", "politi",
            "nødetatene", "patrulje", "patruljer", "brann", "og", "en", "et", "også", "nedenfor",
            "ovenfor", "krysset", "mellom", "etter", "melding", "trafikkulykke", "trafikkuhell"}

# Gate nevnt som retning/avkjøring, ikke som hendelsessted
RETNINGSKONTEKST = re.compile(
    r"(?:\bmot|\bretning|\bavkjøring\w*(?:\s+(?:mot|til))?|\bkjørte\s+(?:videre\s+)?(?:mot|til)|"
    r"\bløp\s+(?:mot|til)|\bforsvant\s+(?:mot|i\s+retning))\s*$", re.I)


def finn_gatenavn(tekst: str, med_kontekstfilter: bool = False) -> list[str]:
    """Kandidater til gatenavn i fritekst, lengste variant først.
    'Økern Torgvei' gir ['Økern Torgvei', 'Torgvei']; 'Også Kong Oscars gate' gir
    ['Kong Oscars gate', 'Oscars gate'] (stoppord droppes)."""
    tekst = tekst or ""
    funn = []

    def legg_til(ordliste: list[str], start: int):
        if med_kontekstfilter and RETNINGSKONTEKST.search(tekst[max(0, start - 40):start]):
            return  # "avkjøringen mot Maridalsveien" o.l.
        while ordliste and ordliste[0].lower().strip(".") in STOPPORD:
            ordliste = ordliste[1:]
        for i in range(len(ordliste)):
            if len(ordliste) - i >= 1:
                funn.append(" ".join(ordliste[i:]))

    for m in GATE_SAMMENSATT.finditer(tekst):
        # ta med opptil to ord med stor forbokstav rett foran ("Nedre Kalbakkvei", "Økern Torgvei")
        foran = re.search(r"((?:[A-ZÆØÅ][\wæøåéü\.]*\s){0,2})$", tekst[:m.start()])
        ord_ = (foran.group(1).split() if foran else []) + [m.group(0)]
        legg_til(ord_, m.start() - (len(foran.group(1)) if foran else 0))
    for m in GATE_SEPARAT.finditer(tekst):
        legg_til(m.group(1).split() + [m.group(2)], m.start())

    sett, ut = set(), []
    for f in funn:
        if norm(f) not in sett and len(f) > 3 and f[0].isupper():
            sett.add(norm(f))
            ut.append(f)
    return ut


def finn_husnummer(tekst: str, gate: str) -> tuple[str, str] | None:
    """'Trondheimsveien 33' -> ('33', ''), 'Steenstrups gate 1b' -> ('1', 'b').
    Ignorerer tall som er etasje, km/t, antall osv."""
    m = re.search(re.escape(gate) + r"\s+(\d{1,4})\s?([A-Za-z])?(?![\w])(?!\s*(?:etasje|km|kmt|personer|biler|år))",
                  tekst or "", re.I)
    if not m:
        return None
    return m.group(1), (m.group(2) or "")


KRYSS_SEP = re.compile(r"\s*(?:/|\s[xX]\s|\s+og\s+)\s*")


def finn_kryss(tekst: str) -> list[tuple[str, str]]:
    """Gatepar som nevnes som kryss: 'Louises gate/Ullevålsveien', 'Økernveien x Kjølberggata',
    'krysset Nedre Prinsdalsvei og Høydalsveien'."""
    par = []
    tekst = tekst or ""
    # ett gatenavn: opptil tre ord med stor forbokstav + siste ord; krysser ikke punktum
    navn = r"(?:[A-ZÆØÅ][\wæøåéü]*\s){0,3}[A-ZÆØÅ]?[\wæøåéü]+"
    for m in re.finditer(rf"({navn})(?:\s*/\s*|\s[xX]\s)({navn})", tekst):
        par.append((m.group(1), m.group(2)))
    for m in re.finditer(rf"[Kk]rysset\s+({navn})\s+og\s+({navn})", tekst):
        par.append((m.group(1), m.group(2)))
    ut = []
    for a, b in par:
        ga, gb = finn_gatenavn(a), finn_gatenavn(b)
        if ga and gb:
            ut.append((ga[0], gb[0]))
    return ut


KONTROLL = re.compile(
    r"\b(trafikkontroll|trafikk-kontroll|fartskontroll|laserkontroll|hastighetskontroll|"
    r"ruskontroll|aksjon skolevei|trafikkorpset har avholdt)\w*", re.I)


def er_kontroll(rad: dict) -> bool:
    """Planlagte trafikkontroller (forelegg-oppsummeringer) er ikke hendelser noen trenger varsel om."""
    return str(rad.get("kategori")) == "Trafikk" and bool(KONTROLL.search(rad.get("tekst") or ""))


def omradedeler(omrade: str | None, kommune: str) -> list[str]:
    """Del opp area-feltet ('Grünerløkka, Oslo', 'Mosseveien V/ Ulvøya' e.l.) og fjern kommunenavnet."""
    if not omrade or str(omrade) == "None":
        return []
    tekst = re.sub(r"\s+[Vv](?:/|\.|ed)\s*", ", ", str(omrade))  # "Mosseveien V/ Ulvøya", "X ved Y"
    deler = [d.strip(" .") for d in re.split(r"[,/;]| - ", tekst) if d.strip(" .")]
    ut = []
    for d in deler:
        uten_vei = VEIPREFIKS.sub("", d).strip()
        if uten_vei and uten_vei != d:
            ut.append(uten_vei)  # "E6 Furuset" -> "Furuset"
        elif uten_vei:
            ut.append(d)
    return [d for d in ut if norm(d) != norm(kommune)]


LANG_GATE_M = 1000  # gater med større usikkerhet enn dette forsøkes begrenset til området


def plasser(rad: dict, geo: Geokoder, kommune: str) -> dict:
    """Prøver i rekkefølge: eksakt adresse -> kryss -> gate (område/tekst, evt. begrenset
    til området) -> stedsnavn -> kun kommune. Velger alltid det mest presise som finnes."""
    deler = omradedeler(rad["omrade"], kommune)
    tekst = rad["tekst"] or ""

    # Område som stedsnavn (ikke gate) – brukes både som reserve og til å begrense lange gater
    omrade_sted = None
    for d in deler:
        res = geo.sted(d)
        if res and res.get("kilde") == "stedsnavn":
            omrade_sted = {**res, "treff": d}
            break

    def gatekandidater_fra_omrade():
        for d in deler:
            # hele delen først ("Nedre Kalbakkvei"), så kandidater inni den
            kand = ([d] if re.search(r"(vei|veg|gate|gata|plass|torg|allé|bakken|stien)$", d, re.I) else [])
            yield from kand + [g for g in finn_gatenavn(d) if g not in kand]

    def gatekandidater_fra_tekst():
        yield from finn_gatenavn(tekst, med_kontekstfilter=True)

    # 1) Eksakt adresse (gate + husnummer)
    for kilde_tekst, kandidater in ((rad["omrade"] or "", gatekandidater_fra_omrade()),
                                    (tekst, gatekandidater_fra_tekst())):
        for g in kandidater:
            nr = finn_husnummer(kilde_tekst, g)
            if nr:
                res = geo.adresse(g, *nr)
                if res:
                    return {**res, "treff": f"{g} {nr[0]}{nr[1]}", "metode": "adresse"}

    # 2) Kryss mellom to gater
    for a, b in finn_kryss(f"{rad['omrade'] or ''} . {tekst}"):
        pa, pb = geo.gate_punkter(a), geo.gate_punkter(b)
        if pa and pb:
            res = kryss_mellom(pa[1], pb[1])
            if res:
                return {**res, "treff": f"{pa[0]} x {pb[0]}", "metode": "kryss"}

    # 3) Gate fra område-feltet, deretter fra teksten
    for metode, kandidater in (("gate (area)", gatekandidater_fra_omrade()),
                               ("gate (tekst)", gatekandidater_fra_tekst())):
        for g in kandidater:
            pkt = geo.gate_punkter(g)
            if not pkt:
                continue
            navn, punkter = pkt
            res = {**oppsummer_punkter(punkter, kilde="gate"), "treff": navn, "metode": metode}
            # 3b) Lang gate: bruk bare delen nær området
            if res["usikkerhet_m"] > LANG_GATE_M and omrade_sted:
                radius = max(omrade_sted["usikkerhet_m"], 800.0)
                begrenset = begrens_til_omrade(punkter, omrade_sted, radius)
                if begrenset:
                    res = {**begrenset, "treff": f"{navn} ved {omrade_sted['treff']}", "metode": "gate+område"}
            # 3c) Fortsatt mindre presist enn området? Da er området bedre.
            if omrade_sted and res["usikkerhet_m"] > omrade_sted["usikkerhet_m"]:
                return {**omrade_sted, "metode": "stedsnavn (area)"}
            return res

    # 4) Stedsnavn fra område-feltet
    if omrade_sted:
        return {**omrade_sted, "metode": "stedsnavn (area)"}

    # 5) Bare kommune
    return {"lat": None, "lon": None, "usikkerhet_m": None, "kilde": "kommune",
            "detalj": "", "treff": rad["omrade"] or "", "metode": "kun kommune"}


# --------------------------------------------------------------------------- rapport

def lag_rapport(rader: list[dict], kommune: str, timespan: str, stedstyper: Counter,
                radius_brukt: dict | None = None) -> str:
    radius_brukt = radius_brukt or {}
    alle = rader
    kontroller = [r for r in alle if r.get("kontroll")]
    rader = [r for r in alle if not r.get("kontroll")]
    n = len(rader)
    if n == 0:
        return "Ingen hendelser funnet for valgt kommune."
    metoder = Counter(r["metode"] for r in rader)
    linjer = [
        f"# Presisjonstest – {kommune} ({timespan})",
        "",
        f"Antall hendelser: **{n}** (i tillegg {len(kontroller)} planlagte trafikkontroller, "
        "som er holdt utenfor alle tall under)",
        "",
        "## Hvordan hendelsene ble plassert",
        "",
        "| Metode | Antall | Andel |",
        "|---|---:|---:|",
    ]
    for m in ["adresse", "kryss", "gate (area)", "gate (tekst)", "gate+område",
              "stedsnavn (area)", "kun kommune"]:
        c = metoder.get(m, 0)
        linjer.append(f"| {m} | {c} | {c / n:.0%} |")

    linjer += ["", "## Andel som kan plasseres innenfor gitt usikkerhet", "",
               "| Usikkerhet ≤ | Andel av alle hendelser |", "|---:|---:|"]
    for t in TERSKLER_M:
        c = sum(1 for r in rader if r["usikkerhet_m"] is not None and r["usikkerhet_m"] <= t)
        linjer.append(f"| {t} m | {c / n:.0%} |")

    # per kategori
    per_kat = defaultdict(list)
    for r in rader:
        per_kat[str(r["kategori"])].append(r)
    linjer += ["", "## Per kategori (andel med usikkerhet ≤ 500 m / ≤ 1000 m)", "",
               "| Kategori | Antall | ≤ 500 m | ≤ 1000 m |", "|---|---:|---:|---:|"]
    for kat, rs in sorted(per_kat.items(), key=lambda kv: -len(kv[1])):
        k = len(rs)
        a500 = sum(1 for r in rs if r["usikkerhet_m"] is not None and r["usikkerhet_m"] <= 500)
        a1000 = sum(1 for r in rs if r["usikkerhet_m"] is not None and r["usikkerhet_m"] <= 1000)
        linjer.append(f"| {kat} | {k} | {a500 / k:.0%} | {a1000 / k:.0%} |")

    if stedstyper:
        linjer += ["", "## Stedstyper fra stedsnavn-API-et (juster STEDSTYPE_RADIUS ved behov)", "",
                   "| Navneobjekttype | Antall | Antatt radius |", "|---|---:|---:|"]
        for typ, c in stedstyper.most_common():
            radius = radius_brukt.get(typ, STEDSTYPE_RADIUS.get(typ, STANDARD_STEDSRADIUS))
            linjer.append(f"| {typ} | {c} | {radius:.0f} m |")

    uplassert = Counter(str(r["omrade"]) for r in rader if r["metode"] == "kun kommune")
    if uplassert:
        linjer += ["", "## Vanligste områder som ikke lot seg plassere", ""]
        for omr, c in uplassert.most_common(15):
            linjer.append(f"- {omr} ({c})")

    linjer += ["", "## Merknader", "",
               "- adresse: gate + husnummer slått opp eksakt (±25 m).",
               "- kryss: nærmeste adressepunkter på to gater som nevnes sammen ('A/B', 'A x B', 'krysset A og B').",
               "- gate+område: lang gate begrenset til adressene nær stedsnavnet i områdefeltet.",
               "- Usikkerhet for gater = 90-persentil avstand fra gatens midtpunkt til adressene langs den.",
               "- Er en gate mindre presis enn områdefeltet, brukes området i stedet.",
               "- Gater nevnt som retning/avkjøring ('avkjøringen mot X', 'kjørte mot X') hoppes over.",
               "- Usikkerhet for stedsnavn er antatt per stedstype, ikke målt.",
               "- Gatenavn i teksten kan være feiltreff (f.eks. en gate nevnt som rømningsretning). "
               "Se stikkprover.html.",
               ]
    return "\n".join(linjer)


# --------------------------------------------------------------------------- stikkprøver

def skriv_stikkprover(rader: list[dict], antall: int, fil: str = "stikkprover.html") -> None:
    """Lager en leservennlig side med tilfeldige 'gate (tekst)'-treff for manuell kontroll.
    Gatenavnet som ble brukt er uthevet i meldingsteksten. Vurderingene lagres i nettleseren."""
    kandidater = [r for r in rader if not r.get("kontroll")
                  and r["metode"] in ("adresse", "kryss", "gate (tekst)", "gate (area)", "gate+område")]
    utvalg = random.Random(42).sample(kandidater, min(antall, len(kandidater)))
    kort = []
    for i, r in enumerate(utvalg, 1):
        tekst = html.escape(r["tekst"] or "")
        if r["treff"]:
            for bit in re.split(r"\s+(?:x|ved)\s+", str(r["treff"])):
                bit = html.escape(re.sub(r"\s+\d+\w?$", "", bit))
                if len(bit) > 2:
                    tekst = re.sub(re.escape(bit), lambda m: f"<mark>{m.group(0)}</mark>", tekst, flags=re.I)
        tekst = tekst.replace("\n", "<br>")
        kart = (f'<a href="{r["kart"]}" target="_blank">Åpne i kart ↗</a>' if r.get("kart") else "")
        kort.append(f"""
<section class="kort" data-id="{html.escape(str(r['id']))}">
  <header><span class="nr">#{i}</span> <b>{html.escape(str(r['kategori']))}</b> · {html.escape(r['metode'])}
    · område: {html.escape(str(r['omrade']))} · treff: <b>{html.escape(str(r['treff']))}</b>
    · ±{r['usikkerhet_m'] or '–'} m · {kart}</header>
  <p>{tekst}</p>
  <div class="valg">
    <label><input type="radio" name="v{i}" value="riktig"> Riktig sted</label>
    <label><input type="radio" name="v{i}" value="feil"> Feil sted</label>
    <label><input type="radio" name="v{i}" value="usikker"> Usikker</label>
  </div>
</section>""")
    side = f"""<!DOCTYPE html><html lang="no"><head><meta charset="utf-8">
<title>Stikkprøver – gatebaserte plasseringer</title>
<style>
 body{{font:16px/1.5 -apple-system,system-ui,sans-serif;max-width:860px;margin:2rem auto;padding:0 1rem;color:#222}}
 .kort{{border:1px solid #ddd;border-radius:10px;padding:1rem 1.2rem;margin:1rem 0}}
 header{{font-size:14px;color:#555}} .nr{{color:#999}} mark{{background:#ffe58a;padding:0 2px}}
 .valg label{{margin-right:1.2rem;font-size:14px}} #sum{{position:sticky;top:0;background:#fff;padding:.6rem 0;border-bottom:1px solid #eee}}
</style></head><body>
<h1>Stikkprøver: gatebaserte plasseringer</h1>
<p>Les meldingen og vurder om det uthevede gatenavnet er <i>der hendelsen skjedde</i>
(ikke f.eks. retningen noen forsvant i).</p>
<div id="sum"></div>
{''.join(kort)}
<script>
const svar = {{}};
function oppdater(){{
  const v = Object.values(svar), n = v.length;
  const r = v.filter(x=>x==="riktig").length, f = v.filter(x=>x==="feil").length;
  document.getElementById("sum").textContent =
    `Vurdert ${{n}} av {len(utvalg)} · riktig ${{r}} · feil ${{f}} · usikker ${{n-r-f}}` +
    (r+f ? ` · treffsikkerhet ${{Math.round(100*r/(r+f))}} %` : "");
}}
document.querySelectorAll("input[type=radio]").forEach(el => el.addEventListener("change", e => {{
  svar[e.target.name] = e.target.value; oppdater();
}}));
oppdater();
</script></body></html>"""
    Path(fil).write_text(side, "utf-8")


# --------------------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--kommune", default="Oslo")
    ap.add_argument("--kommunenummer", default="0301")
    ap.add_argument("--timespan", default="LastQuarter",
                    help="timeSpanType til Politiloggen-API-et (f.eks. LastQuarter)")
    ap.add_argument("--page-size", type=int, default=200)
    ap.add_argument("--max-threads", type=int, default=None)
    ap.add_argument("--refresh", action="store_true", help="hent politiloggen på nytt")
    ap.add_argument("--sample", action="store_true", help="skriv ut én rå tråd og avslutt")
    ap.add_argument("--stikkprover", type=int, default=25,
                    help="antall tilfeldige gatebaserte treff i stikkprover.html")
    ap.add_argument("--test-sted", metavar="NAVN", help="slå opp ett stedsnavn, vis råsvar og avslutt")
    args = ap.parse_args()

    DATA_DIR.mkdir(exist_ok=True)

    if args.test_sted:
        params = {"sok": args.test_sted, "knr": args.kommunenummer, "utkoordsys": 4258,
                  "treffPerSide": 5, "fuzzy": "false"}
        rå = get_json(STEDSNAVN_URLER[0], params)
        print(json.dumps(rå, ensure_ascii=False, indent=2)[:3000])
        print("\nTolket som:", Geokoder(args.kommunenummer)._stedsnavn_sok(args.test_sted))
        return

    if args.sample:
        data = get_json(POLITILOGG_URL, {"take": 1, "skip": 0, "sortByEnum": "LastMessageOn",
                                         "timeSpanType": args.timespan})
        print(json.dumps(data, ensure_ascii=False, indent=2)[:6000])
        return

    if args.refresh or not THREADS_FILE.exists():
        print("Henter tråder fra Politiloggen ...")
        trader = hent_trader(args.timespan, args.page_size, args.max_threads)
        THREADS_FILE.write_text(json.dumps(trader, ensure_ascii=False), "utf-8")
    else:
        trader = json.loads(THREADS_FILE.read_text("utf-8"))
        print(f"Bruker cachede tråder ({len(trader)}). Bruk --refresh for å hente på nytt.")

    alle = [trad_til_rad(t) for t in trader]
    har_kommune = any(r["kommune"] for r in alle)
    if har_kommune:
        rader = [r for r in alle if norm(str(r["kommune"])) == norm(args.kommune)]
    else:
        print("Advarsel: fant ikke kommunefelt i svaret – filtrerer på distrikt i stedet. "
              "Kjør --sample og juster FELT_KOMMUNE.")
        rader = [r for r in alle if norm(args.kommune) in norm(str(r["distrikt"]))]
    print(f"{len(rader)} av {len(alle)} tråder gjelder {args.kommune}.")
    if not rader:
        kommuner = Counter(str(r["kommune"]) for r in alle).most_common(10)
        print("Vanligste kommuneverdier i datasettet:", kommuner)
        return

    geo = Geokoder(args.kommunenummer)
    stedstyper = Counter()
    radius_brukt: dict = {}
    for i, r in enumerate(rader, 1):
        r["kontroll"] = er_kontroll(r)
        r.update(plasser(r, geo, args.kommune))
        if r["kilde"] == "stedsnavn":
            stedstyper[r["detalj"]] += 1
            radius_brukt[r["detalj"]] = r["usikkerhet_m"]
        if i % 50 == 0:
            print(f"  plassert {i}/{len(rader)} ...", end="\r", flush=True)
    print()
    geo.lagre()

    with open("resultat.csv", "w", newline="", encoding="utf-8") as f:
        felt = ["id", "tid", "kategori", "kontroll", "omrade", "metode", "treff", "usikkerhet_m",
                "lat", "lon", "kart", "tekst"]
        w = csv.DictWriter(f, fieldnames=felt, extrasaction="ignore")
        w.writeheader()
        for r in rader:
            r["kart"] = (f"https://www.google.com/maps?q={r['lat']:.6f},{r['lon']:.6f}"
                         if r["lat"] is not None else "")
            r["usikkerhet_m"] = round(r["usikkerhet_m"]) if r["usikkerhet_m"] is not None else ""
            w.writerow({**r, "tekst": re.sub(r"\s*\n\s*", " / ", r["tekst"] or "")})
        # gjør usikkerhet numerisk igjen for rapporten
        for r in rader:
            r["usikkerhet_m"] = float(r["usikkerhet_m"]) if r["usikkerhet_m"] != "" else None

    if geo.feilede:
        print(f"Advarsel: {geo.feilede} oppslag feilet (nettverk/struping) og ble ikke lagret. "
              "Kjør skriptet på nytt for å prøve dem igjen.")
    rapport = lag_rapport(rader, args.kommune, args.timespan, stedstyper, radius_brukt)
    Path("oppsummering.md").write_text(rapport, "utf-8")
    print("\n" + rapport)

    stikk = random.sample(rader, min(20, len(rader)))
    print("\n## 20 tilfeldige stikkprøver (sjekk at plasseringen gir mening)")
    for r in stikk:
        print(f"- [{r['metode']}] {r['omrade']!s:<25} -> {r['treff']!s:<30} "
              f"±{r['usikkerhet_m'] or '–'} m | {r['tekst'][:90]}")
    skriv_stikkprover(rader, args.stikkprover)
    print("\nFiler: resultat.csv, oppsummering.md, stikkprover.html, presisjonsdata/")


if __name__ == "__main__":
    main()
