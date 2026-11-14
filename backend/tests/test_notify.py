"""M1 step 7: the notifier and push (spec §6.2, §7.4, §8.7; D2, D6, D7), with a mocked Expo API.

Time is controlled: the notifier gets a fixed clock, and each event its own first_message_at and
ingested_at. Times are in Europe/Oslo unless stated. 2026-11-16 is a Monday.
"""

from __future__ import annotations

import itertools
import json
import re
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import pytest
import respx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.notify.copy import DISTRICT_BODY, distance_text, push_body, push_title
from app.notify.expo import ExpoClient
from app.notify.notifier import Notifier, NotifyResult
from app.notify.rules import Facts, in_window, why_not
from app.settings import Settings
from tests.test_match_rules import CENTER

OSLO = ZoneInfo("Europe/Oslo")
PUSH_URL = "https://exp.host/--/api/v2/push/send"
RECEIPTS_URL = "https://exp.host/--/api/v2/push/getReceipts"
SKOLE_WINDOW = {"days": [1, 2, 3, 4, 5], "from": "08:00", "to": "16:00"}
_ids = itertools.count()


def oslo(day: int, hh: int, mm: int = 0, ss: int = 0) -> datetime:
    return datetime(2026, 11, day, hh, mm, ss, tzinfo=OSLO)


class Conn:
    """engine.begin() over the test connection: a savepoint per transaction."""

    def __init__(self, conn: AsyncConnection) -> None:
        self.conn = conn

    @asynccontextmanager
    async def begin(self) -> AsyncIterator[AsyncConnection]:
        async with self.conn.begin_nested():
            yield self.conn


class Expo:
    """A fake Expo API: records sends, answers tickets and receipts from the test's settings."""

    def __init__(self) -> None:
        self.sent: list[list[dict[str, Any]]] = []
        self.receipt_requests: list[list[str]] = []
        self.ticket_errors: dict[str, str] = {}  # token → error code
        self.receipts: dict[str, dict[str, Any]] = {}
        self.fail = False

    def send(self, request: httpx.Request) -> httpx.Response:
        if self.fail:
            return httpx.Response(503)
        batch = json.loads(request.content)
        self.sent.append(batch)
        tickets = []
        for m in batch:
            err = self.ticket_errors.get(m["to"])
            if err:
                tickets.append({"status": "error", "message": err, "details": {"error": err}})
            else:
                tickets.append({"status": "ok", "id": f"ticket-{len(self.sent)}-{len(tickets)}"})
        return httpx.Response(200, json={"data": tickets})

    def get_receipts(self, request: httpx.Request) -> httpx.Response:
        ids = json.loads(request.content)["ids"]
        self.receipt_requests.append(ids)
        return httpx.Response(200, json={"data": {i: self.receipts[i] for i in ids if i in self.receipts}})

    @property
    def messages(self) -> list[dict[str, Any]]:
        return [m for b in self.sent for m in b]


class Env:
    def __init__(self, db: AsyncConnection, expo: Expo, http: httpx.AsyncClient) -> None:
        self.db = db
        self.expo = expo
        self.http = http
        self.now = oslo(16, 12)

    def notifier(self, *, dry_run: bool = False, **settings: Any) -> Notifier:
        s = Settings(push_dry_run=dry_run, **settings)
        client = ExpoClient(self.http, PUSH_URL, RECEIPTS_URL, sleep=_no_sleep)
        return Notifier(s, client, clock=lambda: self.now)

    async def run(self, notifier: Notifier | None = None) -> NotifyResult:
        return await (notifier or self.notifier()).run(Conn(self.db))

    async def device(self, token: str | None = "auto", tz: str = "Europe/Oslo") -> uuid.UUID:
        did = uuid.uuid4()
        if token == "auto":
            token = f"ExponentPushToken[{did.hex[:12]}]"
        await self.db.execute(
            text("INSERT INTO devices (id, secret_hash, push_token, tz) VALUES (:id, :h, :t, :tz)"),
            {"id": did, "h": did.hex, "t": token, "tz": tz},
        )
        return did

    async def token(self, device: uuid.UUID) -> str | None:
        return (
            await self.db.execute(text("SELECT push_token FROM devices WHERE id = :d"), {"d": device})
        ).scalar()

    async def place(
        self,
        device: uuid.UUID,
        *,
        label: str = "Skolen",
        radius: int = 1000,
        categories: list[str] | None = None,
        window: dict[str, Any] | None = None,
        push: bool = True,
        knr: str = "0301",
        created: datetime | None = None,
    ) -> uuid.UUID:
        pid = uuid.uuid4()
        await self.db.execute(
            text("""
                INSERT INTO places (id, device_id, label, template, center, radius_m, categories, time_window,
                                    push, kommunenummer, created_at)
                VALUES (:id, :d, :label, 'skole',
                        ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography, :r, :c,
                        CAST(:tw AS jsonb), :push, :knr, :created)
            """),
            {"id": pid, "d": device, "label": label, "lat": CENTER[0], "lon": CENTER[1], "r": radius,
             "c": categories or ["Vold", "Brann", "Savnet", "Ro og orden"],
             "tw": json.dumps(window or {"all": True}), "push": push, "knr": knr,
             "created": created or self.now - timedelta(days=1)},
        )  # fmt: skip
        return pid

    async def event(
        self,
        *,
        first: datetime | None = None,
        detected_after: timedelta = timedelta(minutes=2),
        distance: float | None = 150,
        category: str = "Brann",
        severity: str = "severe",
        tier: str = "gate",
        scope: str = "kommune",
        district: str = "Oslo Politidistrikt",
        area: str | None = "Kampen",
        match: str | None = "Hølandsgata",
        active: bool | None = True,
        message: str = "Røykutvikling fra leilighet i tredje etasje.",
    ) -> str:
        eid = f"n-{next(_ids)}"
        first = first or self.now - detected_after
        geom = (
            "ST_Project(ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography, "
            "CAST(:d AS float8), radians(30))"
            if distance is not None
            else "NULL"
        )
        notice = scope == "distrikt"
        await self.db.execute(
            text(f"""
                INSERT INTO events (id, category, severity, first_message_at, last_message_at, raw, geom,
                                    uncertainty_m, precision_tier, geocode_method, geocode_match, area, scope,
                                    kommunenummer, district, municipality, is_active, ingested_at)
                VALUES (:id, :cat, :sev, :first, :first, '{{}}', {geom}, :u, :tier, :method, :match, :area,
                        :scope, :knr, :district, :municipality, :active, :ingested)
            """),
            {"id": eid, "cat": category, "sev": severity, "first": first, "lat": CENTER[0], "lon": CENTER[1],
             "d": distance, "u": None if notice else 100, "tier": None if notice else tier,
             "method": None if notice else "gate_area", "match": None if notice else match,
             "area": None if notice else area, "scope": scope, "knr": None if notice else "0301",
             "district": district, "municipality": "Oslo politidistrikt" if notice else "Oslo",
             "active": active, "ingested": first + detected_after},
        )  # fmt: skip
        await self.db.execute(
            text("INSERT INTO event_messages (event_id, seq, created_at, text) VALUES (:e, 0, :c, :t)"),
            {"e": eid, "c": first, "t": message},
        )
        return eid

    async def notifications(self, **where: Any) -> list[Any]:
        cond = " AND ".join(f"n.{k} = :{k}" for k in where) or "true"
        return (
            await self.db.execute(
                text(f"""
                    SELECT n.*, p.device_id FROM notifications n JOIN places p ON p.id = n.place_id
                    WHERE {cond} ORDER BY n.id
                """),
                where,
            )
        ).all()


async def _no_sleep(_: float) -> None:
    return None


@pytest.fixture
async def env(db: AsyncConnection) -> AsyncIterator[Env]:
    # Nothing from earlier tests is pending: everything already stored counts as handled.
    await db.execute(text("UPDATE events SET notified_at = now() WHERE notified_at IS NULL"))
    expo = Expo()
    async with respx.mock(assert_all_called=False) as router, httpx.AsyncClient() as http:
        router.post(PUSH_URL).mock(side_effect=expo.send)
        router.post(RECEIPTS_URL).mock(side_effect=expo.get_receipts)
        yield Env(db, expo, http)


# --- the basic path ------------------------------------------------------------------------


async def test_a_severe_matching_event_is_pushed_once(env: Env) -> None:
    device = await env.device()
    pid = await env.place(device, label="Hjemme")
    eid = await env.event()
    res = await env.run()
    assert (res.events, res.planned, res.sent, res.failed) == (1, 1, 1, 0)
    [m] = env.expo.messages
    assert m["to"] == await env.token(device)
    assert m["title"] == "Brann ca. 150 m fra Hjemme"
    assert m["body"] == "Hølandsgata, Kampen. Brann, pågår. Presisjon: gate."
    assert m["data"] == {"event_id": eid, "place_id": str(pid)}
    [n] = await env.notifications()
    assert n.status == "sent" and n.ticket_id == "ticket-1-0" and n.event_id == eid and n.place_id == pid

    # A second cycle, and a restart (a new notifier), push nothing more.
    assert (await env.run()).events == 0
    await env.db.execute(text("UPDATE events SET notified_at = NULL WHERE id = :e"), {"e": eid})
    res = await env.run(env.notifier())
    assert res.events == 1 and res.planned == 0 and res.skipped == {"already pushed": 1}
    assert len(env.expo.messages) == 1
    assert len(await env.notifications()) == 1


async def test_updates_and_later_placements_never_push(env: Env) -> None:
    device = await env.device()
    await env.place(device)
    eid = await env.event(distance=5000)  # first stored outside the place
    assert (await env.run()).planned == 0
    # Later improved into the place (a thread update or the step 1 command): already handled.
    await env.db.execute(
        text("""
            UPDATE events SET geom = ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography,
                              updated_at = now(), last_message_at = last_message_at + interval '5 minutes'
            WHERE id = :e
        """),
        {"e": eid, "lat": CENTER[0], "lon": CENTER[1]},
    )
    assert (await env.run()).events == 0
    assert env.expo.messages == []


async def test_events_stored_before_the_push_migration_are_never_pushed(env: Env) -> None:
    device = await env.device()
    await env.place(device)
    eid = await env.event()
    await env.db.execute(
        text("UPDATE events SET notified_at = now(), ingested_at = NULL WHERE id = :e"), {"e": eid}
    )
    assert (await env.run()).events == 0
    assert env.expo.messages == []


async def test_dry_run_logs_instead_of_sending(env: Env, caplog: pytest.LogCaptureFixture) -> None:
    device = await env.device()
    await env.place(device, label="Hjemme")
    await env.event()
    caplog.set_level("INFO", logger="app.notify")
    res = await env.run(env.notifier(dry_run=True))
    assert res.sent == 1 and env.expo.sent == []
    assert [n.status for n in await env.notifications()] == ["dry_run"]
    assert "Brann ca. 150 m fra Hjemme" in caplog.text
    assert "ExponentPushToken" not in caplog.text  # tokens are never logged


# --- the §6.2 push rules -------------------------------------------------------------------


async def test_fourth_severe_event_in_a_day_is_not_pushed(env: Env) -> None:
    device = await env.device()
    pid = await env.place(device)
    for minute in range(4):
        env.now = oslo(16, 12, minute)
        await env.event()
        await env.run()
    assert len(env.expo.messages) == 3
    # The next calendar day in Oslo has room again; the limit is per place.
    env.now = oslo(17, 0, 1)
    await env.event()
    other = await env.place(device, label="Annet sted")
    await env.run()
    assert len(env.expo.messages) == 5
    assert {m["data"]["place_id"] for m in env.expo.messages[3:]} == {str(pid), str(other)}


async def test_the_day_is_the_devices_calendar_day(env: Env) -> None:
    # 23:30 in Oslo on Monday is already Tuesday in Tokyo (UTC+9): Monday's pushes don't count there.
    device = await env.device(tz="Asia/Tokyo")
    await env.place(device)
    for minute in range(3):
        env.now = datetime(2026, 11, 16, 14, minute, tzinfo=OSLO)  # 22:0x Tokyo, Monday
        await env.event()
        await env.run()
    env.now = oslo(16, 17, 30)  # 01:30 Tuesday in Tokyo
    await env.event()
    await env.run()
    assert len(env.expo.messages) == 4


@pytest.mark.parametrize(
    ("first", "pushed"),
    [
        (oslo(16, 7, 59), False),
        (oslo(16, 8, 0), True),
        (oslo(16, 15, 59, 59), True),
        (oslo(16, 16, 0), False),  # the window is half-open: 16:00 is outside
        (oslo(14, 12, 0), False),  # Saturday
    ],
)
async def test_time_window_edges(env: Env, first: datetime, pushed: bool) -> None:
    device = await env.device()
    await env.place(device, window=SKOLE_WINDOW)
    env.now = first + timedelta(minutes=2)
    await env.event(first=first)
    res = await env.run()
    assert (res.planned == 1) == pushed, res
    if not pushed:
        assert res.skipped == {"outside time window": 1}


async def test_time_window_uses_the_devices_tz(env: Env) -> None:
    # 15:30 in Oslo is 14:30 in London: inside 08:00-15:00 there, outside it in Oslo.
    window = {"days": [1, 2, 3, 4, 5], "from": "08:00", "to": "15:00"}
    london = await env.device(tz="Europe/London")
    oslo_device = await env.device()
    await env.place(london, window=window)
    await env.place(oslo_device, window=window)
    env.now = oslo(16, 15, 32)
    await env.event(first=oslo(16, 15, 30))
    await env.run()
    assert [m["to"] for m in env.expo.messages] == [await env.token(london)]


@pytest.mark.parametrize(("age_min", "pushed"), [(30, True), (31, False)])
async def test_first_message_age_at_detection(env: Env, age_min: int, pushed: bool) -> None:
    device = await env.device()
    await env.place(device)
    await env.event(detected_after=timedelta(minutes=age_min))
    res = await env.run()
    assert (res.planned == 1) == pushed
    if not pushed:
        assert res.skipped == {"too old at detection": 1}


async def test_an_event_the_notifier_sees_late_is_not_pushed(env: Env) -> None:
    device = await env.device()
    await env.place(device)
    await env.event(detected_after=timedelta(minutes=1))
    env.now += timedelta(minutes=11)  # the worker was down between ingest and notify
    res = await env.run()
    assert res.events == 1 and res.late == 1 and res.planned == 0
    assert (await env.run()).events == 0  # and it is handled


@pytest.mark.parametrize(
    ("setup", "reason"),
    [
        ("normal", None),
        ("push_off", "push off"),
        ("no_token", "no push token"),
    ],
)
async def test_place_and_device_conditions(env: Env, setup: str, reason: str | None) -> None:
    device = await env.device(token=None if setup == "no_token" else "auto")
    await env.place(device, push=setup != "push_off")
    await env.event()
    res = await env.run()
    assert res.skipped == ({reason: 1} if reason else {})
    assert res.planned == (0 if reason else 1)


async def test_only_severe_matched_events_in_the_places_categories_push(env: Env) -> None:
    device = await env.device()
    await env.place(device, radius=900)
    await env.event(severity="normal")
    await env.event(category="Tyveri")  # not followed
    await env.event(tier="nabolag")  # nabolag needs radius ≥ 1 000
    await env.event(distance=950)  # outside
    await env.event(tier="bydel")  # imprecise nearby is never pushed
    res = await env.run()
    assert res.events == 5 and res.planned == 0 and env.expo.messages == []


async def test_every_matched_place_of_a_device_gets_its_own_push(env: Env) -> None:
    # §6.2 / §8.7 as written: the key is (place, event). Only district notices are once per device.
    device = await env.device()
    await env.place(device, label="Hjemme")
    await env.place(device, label="Skolen")
    await env.event()
    await env.run()
    assert sorted(m["title"] for m in env.expo.messages) == [
        "Brann ca. 150 m fra Hjemme",
        "Brann ca. 150 m fra Skolen",
    ]


# --- district-wide notices (D2) ------------------------------------------------------------


async def stored_oslo_district(env: Env) -> None:
    """The district → municipality map comes from stored events (step 2): one Oslo event."""
    eid = await env.event(distance=50_000, category="Tyveri", severity="normal")
    await env.db.execute(text("UPDATE events SET notified_at = now() WHERE id = :e"), {"e": eid})


async def test_district_savnet_reaches_a_device_once_at_its_oldest_place(env: Env) -> None:
    await stored_oslo_district(env)
    two_places = await env.device()
    oldest = await env.place(two_places, label="Hjemme", created=env.now - timedelta(days=10))
    await env.place(two_places, label="Skolen", created=env.now - timedelta(days=2))
    one_place = await env.device()
    await env.place(one_place, label="Jobben")
    no_savnet = await env.device()
    await env.place(no_savnet, categories=["Brann"])
    elsewhere = await env.device()
    await env.place(elsewhere, knr="5001")  # Trondheim: another district

    eid = await env.event(scope="distrikt", category="Savnet", distance=None)
    res = await env.run()
    assert res.planned == 2
    by_token = {m["to"]: m for m in env.expo.messages}
    assert set(by_token) == {await env.token(two_places), await env.token(one_place)}
    m = by_token[await env.token(two_places)]
    assert m["title"] == "Savnet i Oslo politidistrikt" and m["body"] == DISTRICT_BODY
    assert m["data"] == {"event_id": eid, "place_id": str(oldest)}

    # Run again (as after a restart): still once per device.
    await env.db.execute(text("UPDATE events SET notified_at = NULL WHERE id = :e"), {"e": eid})
    await env.run()
    assert len(env.expo.messages) == 2


async def test_district_savnet_goes_to_the_oldest_place_that_qualifies(env: Env) -> None:
    await stored_oslo_district(env)
    device = await env.device()
    await env.place(device, label="Skolen", window=SKOLE_WINDOW, created=env.now - timedelta(days=10))
    hytta = await env.place(device, label="Hjemme", created=env.now - timedelta(days=2))
    env.now = oslo(16, 20, 0)  # outside Skolen's window
    await env.event(scope="distrikt", category="Savnet", distance=None)
    await env.run()
    assert [m["data"]["place_id"] for m in env.expo.messages] == [str(hytta)]


async def test_other_district_notices_are_never_pushed(env: Env) -> None:
    await stored_oslo_district(env)
    device = await env.device()
    await env.place(device, categories=["Vold", "Brann", "Savnet", "Ro og orden", "Trafikk", "Andre"])
    await env.event(scope="distrikt", category="Trafikk", distance=None)
    await env.event(scope="distrikt", category="Andre hendelser", distance=None)
    res = await env.run()
    assert res.events == 2 and res.planned == 0


# --- Expo: batches, failures and receipts --------------------------------------------------


async def test_pushes_go_in_batches_of_100(env: Env) -> None:
    for _ in range(150):
        await env.place(await env.device())
    await env.event()
    res = await env.run()
    assert res.sent == 150
    assert [len(b) for b in env.expo.sent] == [100, 50]


async def test_send_failure_marks_the_rows_and_never_resends(env: Env) -> None:
    device = await env.device()
    await env.place(device)
    await env.event()
    env.expo.fail = True
    res = await env.run()
    assert res.failed == 1
    assert [n.status for n in await env.notifications()] == ["error:send_failed"]
    env.expo.fail = False
    assert (await env.run()).events == 0
    assert env.expo.messages == []


async def test_ticket_device_not_registered_clears_the_token(env: Env) -> None:
    gone = await env.device()
    ok = await env.device()
    env.expo.ticket_errors[await env.token(gone)] = "DeviceNotRegistered"
    await env.place(gone)
    await env.place(ok)
    await env.event()
    res = await env.run()
    assert (res.sent, res.failed) == (1, 1)
    assert await env.token(gone) is None and await env.token(ok) is not None
    statuses = {n.device_id: n.status for n in await env.notifications()}
    assert statuses == {gone: "error:DeviceNotRegistered", ok: "sent"}


async def test_receipts(env: Env) -> None:
    devices = [await env.device() for _ in range(4)]
    for d in devices:
        await env.place(d)
    await env.event()
    await env.run()
    rows = await env.notifications()
    ticket = {n.device_id: n.ticket_id for n in rows}
    env.expo.receipts = {
        ticket[devices[0]]: {"status": "ok"},
        ticket[devices[1]]: {
            "status": "error",
            "message": "gone",
            "details": {"error": "DeviceNotRegistered"},
        },
        ticket[devices[2]]: {
            "status": "error",
            "message": "rate",
            "details": {"error": "MessageRateExceeded"},
        },
        # devices[3]: no receipt yet
    }
    env.now += timedelta(minutes=14)
    await env.run()
    assert env.expo.receipt_requests == []  # not before 15 minutes

    env.now += timedelta(minutes=2)
    res = await env.run()
    assert (res.receipts_ok, res.receipts_error) == (1, 2)
    status = {n.device_id: n.status for n in await env.notifications()}
    assert status == {
        devices[0]: "ok",
        devices[1]: "error:DeviceNotRegistered",
        devices[2]: "error:MessageRateExceeded",
        devices[3]: "sent",  # asked again next cycle
    }
    assert await env.token(devices[1]) is None
    assert await env.token(devices[2]) is not None

    env.now += timedelta(days=1)
    await env.run()
    status = {n.device_id: n.status for n in await env.notifications()}
    assert status[devices[3]] == "receipt_missing"


# --- copy (D6) -----------------------------------------------------------------------------


def _words(s: str) -> set[str]:
    return {w.lower() for w in re.findall(r"\w+", s)}


async def test_push_text_contains_no_police_text(env: Env) -> None:
    message = "Mann i 40-årene pågrepet etter knivstikking utenfor butikken, vitner bes melde seg."
    device = await env.device()
    await env.place(device, label="Hjemme")
    await env.event(category="Voldshendelse", message=message, area="Kampen", match="Hølandsgata")
    await env.run()
    [m] = env.expo.messages
    leaked = _words(message) & (_words(m["title"]) | _words(m["body"]))
    assert leaked == set(), leaked
    assert m["title"] == "Vold ca. 150 m fra Hjemme"


@pytest.mark.parametrize(
    ("d", "text_"),
    [(0, "50 m"), (24, "50 m"), (149, "150 m"), (151, "150 m"), (174, "150 m"), (176, "200 m"),
     (960, "950 m"),
     (980, "1,0 km"), (1000, "1,0 km"), (1240, "1,2 km"), (1960, "2,0 km")],
)  # fmt: skip
def test_distance_text(d: float, text_: str) -> None:
    assert distance_text(d) == text_


@pytest.mark.parametrize(
    ("kw", "body"),
    [
        ({}, "Hølandsgata, Kampen. Brann, pågår. Presisjon: gate."),
        ({"is_active": False}, "Hølandsgata, Kampen. Brann, avsluttet. Presisjon: gate."),
        ({"is_active": None}, "Hølandsgata, Kampen. Brann. Presisjon: gate."),
        ({"area": "Hølandsgata"}, "Hølandsgata. Brann, pågår. Presisjon: gate."),  # no repeat
        ({"area": None}, "Hølandsgata. Brann, pågår. Presisjon: gate."),
        ({"geocode_method": "stedsnavn", "geocode_match": "Kampen", "precision_tier": "nabolag"},
         "Kampen. Brann, pågår. Presisjon: nabolag."),
        ({"category": "Ulykke"}, "Hølandsgata, Kampen. Ulykke, pågår. Presisjon: gate."),
    ],
)  # fmt: skip
def test_push_body(kw: dict[str, Any], body: str) -> None:
    args: dict[str, Any] = {
        "category": "Brann",
        "is_active": True,
        "precision_tier": "gate",
        "geocode_method": "gate_area",
        "geocode_match": "Hølandsgata",
        "area": "Kampen",
        "municipality": "Oslo",
        "district": "Oslo Politidistrikt",
    }
    assert push_body(**(args | kw)) == body


def test_push_title() -> None:
    assert (
        push_title(category="Brann", distance_m=148, place_label_text="Hjemme")
        == "Brann ca. 150 m fra Hjemme"
    )


# --- the rules as a pure function ----------------------------------------------------------


def facts(**kw: Any) -> Facts:
    base: dict[str, Any] = {
        "severe": True,
        "first_message_at": oslo(16, 12),
        "ingested_at": oslo(16, 12, 2),
        "window": {"all": True},
        "tz": "Europe/Oslo",
        "pushes_today": 0,
        "push_on": True,
        "has_token": True,
    }
    return Facts(**(base | kw))


def test_why_not() -> None:
    assert why_not(facts()) is None
    assert why_not(facts(severe=False)) == "not severe"
    assert why_not(facts(pushes_today=2)) is None
    assert why_not(facts(pushes_today=3)) == "daily limit"
    assert why_not(facts(ingested_at=oslo(16, 12, 30))) is None
    assert why_not(facts(ingested_at=oslo(16, 12, 30, 1))) == "too old at detection"


def test_in_window_across_dst() -> None:
    # 29 March 2026: clocks go forward in Oslo. 08:30 local is 06:30 UTC.
    w = {"days": [7], "from": "08:00", "to": "09:00"}
    assert in_window(w, datetime(2026, 3, 29, 6, 30, tzinfo=ZoneInfo("UTC")), "Europe/Oslo")
    assert not in_window(w, datetime(2026, 3, 29, 7, 30, tzinfo=ZoneInfo("UTC")), "Europe/Oslo")
