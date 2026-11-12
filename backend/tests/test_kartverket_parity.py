"""Parity with research/presisjonstest.py: given the same Kartverket response, the port must
send the same request parameters and produce the same result as the script."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx

from tests.kartverket_samples import ADRESSE_URL, FURUSET, STEDSNAVN_URLS, FakeTime, adresser, make_client
from tests.test_text_parity import ref

KNR = "0301"


def oracle_with_response(monkeypatch: pytest.MonkeyPatch, data: dict[str, Any]) -> list[tuple[str, dict]]:
    """Make the script's get_json return `data`, recording (url, params) of each call."""
    calls: list[tuple[str, dict]] = []

    def fake_get_json(url: str, params: dict, tries: int = 5) -> dict:
        calls.append((url, {k: str(v) for k, v in params.items()}))
        return data

    monkeypatch.setattr(ref, "get_json", fake_get_json)
    return calls


async def port_with_response(data: dict[str, Any], url: str, method: str, *args: str) -> tuple[Any, dict]:
    async with respx.mock(assert_all_mocked=True) as router, httpx.AsyncClient() as http:
        route = router.get(url).mock(return_value=httpx.Response(200, json=data))
        client = make_client(http, FakeTime())
        result = await getattr(client, method)(*args)
        return result, dict(route.calls.last.request.url.params)


def one(typ: str, name: str, point: dict | None, *, top_level_name: bool = False) -> dict:
    """A /navn response with a single hit."""
    hit: dict = {"navneobjekttype": typ}
    if top_level_name:
        hit["skrivemåte"] = name
    else:
        hit["stedsnavn"] = [{"skrivemåte": name}]
    if point is not None:
        hit["representasjonspunkt"] = point
    return {"navn": [hit]}


STEDSNAVN_CASES = {
    "furuset": ("Furuset", FURUSET),
    "case-insensitive": (
        "furuset",
        one("Tettbebyggelse", "Furuset", {"nord": 59.9, "øst": 10.9}, top_level_name=True),
    ),
    "unknown-type": ("Hosle", one("Vik i sjø", "Hosle", {"nord": 59.93, "øst": 10.6})),
    "lat-lon-keys": ("Bryn", one("Gard", "Bryn", {"lat": 59.91, "lon": 10.81})),
    "no-point": ("Bryn", one("Gard", "Bryn", None)),
    "only-other-spelling": ("Bryn", one("Gard", "Brynseng", {"nord": 59.9, "øst": 10.8})),
    "adressenavn": ("Mosseveien", one("Adressenavn", "Mosseveien", {"nord": 59.89, "øst": 10.76})),
    "empty": ("Ingensteds", {"navn": []}),
}


@pytest.mark.parametrize("case", STEDSNAVN_CASES.values(), ids=STEDSNAVN_CASES.keys())
async def test_stedsnavn_parity(monkeypatch: pytest.MonkeyPatch, case: tuple[str, dict]) -> None:
    navn, data = case
    calls = oracle_with_response(monkeypatch, data)
    expected = ref.Geokoder(KNR)._stedsnavn_sok(navn)
    result, params = await port_with_response(data, STEDSNAVN_URLS[0], "stedsnavn", navn, KNR)
    assert result == expected
    assert (STEDSNAVN_URLS[0], params) == calls[0]


ADRESSE_CASES = {
    "two-points": adresser((59.9234567, 10.7712345), (59.92, 10.77)),
    "missing-point": {
        "adresser": [{"adressetekst": "X 1"}, {"representasjonspunkt": {"lat": 59.9, "lon": 10.7}}]
    },
    "empty": {"adresser": []},
}


@pytest.mark.parametrize("data", ADRESSE_CASES.values(), ids=ADRESSE_CASES.keys())
async def test_adresse_punkter_parity(monkeypatch: pytest.MonkeyPatch, data: dict) -> None:
    calls = oracle_with_response(monkeypatch, data)
    expected = ref.Geokoder(KNR)._adresse_punkter("Trondheimsveien")
    result, params = await port_with_response(data, ADRESSE_URL, "adresse_punkter", "Trondheimsveien", KNR)
    assert result == expected
    assert (ADRESSE_URL, params) == calls[0]


@pytest.mark.parametrize(("nummer", "bokstav"), [("33", ""), ("1", "b")])
@pytest.mark.parametrize("data", ADRESSE_CASES.values(), ids=ADRESSE_CASES.keys())
async def test_adresse_eksakt_parity(
    monkeypatch: pytest.MonkeyPatch, data: dict, nummer: str, bokstav: str
) -> None:
    calls = oracle_with_response(monkeypatch, data)
    expected = ref.Geokoder(KNR)._adresse_eksakt("Steenstrups gate", nummer, bokstav)
    result, params = await port_with_response(
        data, ADRESSE_URL, "adresse_eksakt", "Steenstrups gate", nummer, bokstav, KNR
    )
    assert result == expected
    assert (ADRESSE_URL, params) == calls[0]


def test_tables_match_script() -> None:
    from app.geocode import places

    # The script's tables plus only the documented additions, which the script doesn't list.
    assert not set(places.TILLEGG_RADIUS) & set(ref.SCRIPT_STEDSTYPE_RADIUS)
    assert not set(places.TILLEGG_PRIORITET) & set(ref.SCRIPT_STEDSTYPE_PRIORITET)
    assert places.STEDSTYPE_RADIUS == {**ref.SCRIPT_STEDSTYPE_RADIUS, **places.TILLEGG_RADIUS}
    assert places.STANDARD_STEDSRADIUS == ref.STANDARD_STEDSRADIUS
    assert places.STEDSTYPE_PRIORITET == {**ref.SCRIPT_STEDSTYPE_PRIORITET, **places.TILLEGG_PRIORITET}


def _navn(typ: str, lat: float, lon: float, navn: str = "Jessheim") -> dict:
    return {"skrivemåte": navn, "navneobjekttype": typ, "representasjonspunkt": {"nord": lat, "øst": lon}}


@pytest.mark.parametrize(
    "navn, items, typ, radius",
    [
        # Live answers for knr 3209 on 2026-11-12: the script picks the bridge (tie at 50, "bru" < "by").
        ("Jessheim", [("By", 60.1415, 11.17516), ("Bru", 60.14139, 11.17592)], "by", 2500.0),
        ("Gardermoen", [("Bru", 60.19, 11.09), ("Flyplass", 60.1939, 11.1004), ("Mo", 60.2, 11.08)],
         "flyplass", 2500.0),
        # A bridge still wins over a street name, as in the script.
        ("Drammensveien", [("Adressenavn", 59.92, 10.70), ("Bru", 59.91, 10.66)], "bru", 150.0),
    ],
)  # fmt: skip
def test_town_and_airport_beat_a_bridge_of_the_same_name(
    navn: str, items: list[tuple[str, float, float]], typ: str, radius: float
) -> None:
    from app.geocode import places

    data = {"navn": [_navn(t, lat, lon, navn) for t, lat, lon in items]}
    got = places.velg_stedsnavn(data, navn)
    assert got is not None and (got["detalj"], got["usikkerhet_m"]) == (typ, radius)
    if typ != "bru":
        with pytest.MonkeyPatch.context() as mp:  # the unmodified script chose the bridge
            mp.setattr(ref, "STEDSTYPE_PRIORITET", ref.SCRIPT_STEDSTYPE_PRIORITET)
            mp.setattr(places, "STEDSTYPE_PRIORITET", ref.SCRIPT_STEDSTYPE_PRIORITET)
            assert places.velg_stedsnavn(data, navn)["detalj"] == "bru"
