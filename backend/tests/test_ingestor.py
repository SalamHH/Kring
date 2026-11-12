"""Ingestor integration tests (M0 step 7): recorded Oslo threads served by a fake Politiloggen,
recorded Kartverket answers, and the test database."""

from __future__ import annotations

import copy
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
import respx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.geocode.pipeline import Geocoder
from app.ingest.client import PolitiloggenClient
from app.ingest.ingestor import Ingestor
from app.ingest.politiloggen import parse_time
from app.settings import Settings
from tests.kartverket_replay import load_all, replay_handler
from tests.kartverket_samples import FakeTime, make_client
from tests.politiloggen_fixtures import kommuner, page_sample, raw_threads_in

RECORDS = load_all()
SETTINGS = Settings(allowed_fylker=["03"], page_size=50, min_pages=3)
N_OSLO = 120


def by_last_message(threads: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(threads, key=lambda t: t["lastMessageOn"], reverse=True)


def oslo_threads(n: int = N_OSLO) -> list[dict[str, Any]]:
    return copy.deepcopy(by_last_message(raw_threads_in("0301"))[:n])


def other_threads() -> list[dict[str, Any]]:
    """Out-of-scope threads (not Oslo) from the recorded nationwide page."""
    return copy.deepcopy([t for t in page_sample()["messageThreads"] if t["municipality"] != "Oslo"][:30])


@dataclass
class FakePolitiloggen:
    threads: list[dict[str, Any]]
    fail_with: int | None = None
    calls: list[dict[str, str]] = field(default_factory=list)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        params = dict(request.url.params)
        self.calls.append(params)
        if self.fail_with:
            return httpx.Response(self.fail_with)
        skip, take = int(params["skip"]), int(params["take"])
        ordered = by_last_message(self.threads)
        page = ordered[skip : skip + take]
        return httpx.Response(
            200, json={"messageThreads": page, "hasMoreResults": skip + take < len(ordered)}
        )


@dataclass
class Env:
    conn: AsyncConnection
    ingestor: Ingestor
    politi: FakePolitiloggen
    router: respx.MockRouter
    kartverket_fail: list[bool]
    now: list[datetime]
    sleeps: list[float]

    async def cycle(self):
        return await self.ingestor.run_cycle(self.conn)

    async def scalar(self, sql: str, **params: Any) -> Any:
        return (await self.conn.execute(text(sql), params)).scalar()

    def thread(self, tid: str) -> dict[str, Any]:
        return next(t for t in self.politi.threads if t["id"] == tid)

    def kartverket_requests(self) -> int:
        return self.ingestor.kartverket.requests


@pytest.fixture
async def env(db: AsyncConnection) -> AsyncIterator[Env]:
    threads = oslo_threads() + other_threads()
    latest = max(parse_time(t["lastMessageOn"]) for t in threads)
    assert latest is not None
    now = [latest + timedelta(minutes=1)]
    politi = FakePolitiloggen(threads)
    kartverket_fail = [False]
    replay = replay_handler(RECORDS)

    def kartverket(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503) if kartverket_fail[0] else replay(request)

    sleeps: list[float] = []

    async def fake_sleep(s: float) -> None:
        sleeps.append(s)

    async with (
        respx.mock(assert_all_mocked=True, assert_all_called=False) as router,
        httpx.AsyncClient() as http,
    ):
        router.get(SETTINGS.politiloggen_url).mock(side_effect=politi)
        router.get(SETTINGS.kommuneinfo_url, name="kommuneinfo").mock(
            return_value=httpx.Response(200, json=kommuner())
        )
        router.route().mock(side_effect=kartverket)
        ingestor = Ingestor(
            SETTINGS,
            PolitiloggenClient(http, SETTINGS.politiloggen_url, sleep=fake_sleep),
            make_client(http, FakeTime()),
            http,
            clock=lambda: now[0],
        )
        yield Env(db, ingestor, politi, router, kartverket_fail, now, sleeps)


def add_message(t: dict[str, Any], text_: str, minutes: int = 5) -> None:
    last = parse_time(t["lastMessageOn"])
    assert last is not None
    when = (last + timedelta(minutes=minutes)).isoformat()
    seq = max(int(m["id"].rsplit("-", 1)[1]) for m in t["messages"]) + 1
    t["messages"].append({"id": f"{t['id']}-{seq}", "text": text_, "createdOn": when, "updatedOn": when,
                          "type": "Published"})  # fmt: skip
    t["lastMessageOn"] = t["updatedOn"] = when


async def event_with_tier(env: Env, tier: str) -> str:
    tid = await env.scalar(
        "SELECT id FROM events WHERE precision_tier = :t AND geom IS NOT NULL ORDER BY id LIMIT 1", t=tier
    )
    assert tid, f"no {tier} event in the sample"
    return tid


# --- first and repeated cycles -----------------------------------------------------------------


async def test_first_cycle_stores_oslo_threads_only(env: Env) -> None:
    res = await env.cycle()
    assert res.ok and res.errors == 0
    assert res.time_span == "LastQuarter"  # never polled before
    assert res.fetched == N_OSLO + len(other_threads())
    assert res.new == res.in_scope == res.geocoded == N_OSLO
    assert await env.scalar("SELECT count(*) FROM events") == N_OSLO
    assert await env.scalar("SELECT count(*) FROM events WHERE kommunenummer <> '0301'") == 0
    n_msgs = sum(len(t["messages"]) for t in oslo_threads())
    assert await env.scalar("SELECT count(*) FROM event_messages") == n_msgs
    assert await env.scalar("SELECT count(*) FROM events WHERE geocode_method IS NULL") == 0
    assert await env.scalar("SELECT last_success_at FROM ingest_state") == env.now[0]
    # every point has a tier consistent with its stored uncertainty
    assert await env.scalar(
        """SELECT count(*) FROM events WHERE geom IS NOT NULL AND precision_tier <> CASE
             WHEN uncertainty_m <= 500 THEN 'gate' WHEN uncertainty_m <= 1500 THEN 'nabolag'
             ELSE 'bydel' END"""
    ) == 0  # fmt: skip
    assert (
        await env.scalar("SELECT count(*) FROM events WHERE geom IS NULL AND precision_tier <> 'bydel'") == 0
    )


async def test_same_cycle_twice_creates_nothing_and_calls_no_geocoder(env: Env) -> None:
    await env.cycle()
    events, msgs = (
        await env.scalar("SELECT count(*) FROM events"),
        await env.scalar("SELECT count(*) FROM event_messages"),
    )
    updated_at = await env.scalar("SELECT max(updated_at) FROM events")
    requests = env.kartverket_requests()

    env.now[0] += timedelta(minutes=1)
    res = await env.cycle()
    assert res.ok and res.time_span == "LastDay"
    assert (res.new, res.updated, res.unchanged, res.geocoded) == (0, 0, N_OSLO, 0)
    assert env.kartverket_requests() == requests
    assert await env.scalar("SELECT count(*) FROM events") == events
    assert await env.scalar("SELECT count(*) FROM event_messages") == msgs
    assert await env.scalar("SELECT max(updated_at) FROM events") == updated_at


async def test_new_message_is_appended(env: Env) -> None:
    await env.cycle()
    tid = await event_with_tier(env, "gate")
    t = env.thread(tid)
    before = len(t["messages"])
    add_message(t, "Patruljen har avsluttet på stedet.")

    res = await env.cycle()
    assert (res.new, res.updated, res.geocoded) == (0, 1, 0)  # gate tier, same area: no re-geocode
    assert await env.scalar("SELECT count(*) FROM event_messages WHERE event_id = :id", id=tid) == before + 1
    assert await env.scalar(
        "SELECT text FROM event_messages WHERE event_id = :id ORDER BY seq DESC LIMIT 1", id=tid
    ) == "Patruljen har avsluttet på stedet."  # fmt: skip
    assert await env.scalar("SELECT last_message_at FROM events WHERE id = :id", id=tid) == parse_time(
        t["lastMessageOn"]
    )


async def test_changed_area_triggers_regeocode(env: Env) -> None:
    await env.cycle()
    tid = await event_with_tier(env, "gate")
    env.thread(tid)["area"] = None
    res = await env.cycle()
    assert (res.updated, res.geocoded) == (1, 1)
    assert await env.scalar("SELECT area FROM events WHERE id = :id", id=tid) is None


@pytest.mark.parametrize("tier", ["nabolag", "bydel"])
async def test_imprecise_tier_triggers_regeocode_on_update(env: Env, tier: str) -> None:
    await env.cycle()
    tid = await event_with_tier(env, tier)
    add_message(env.thread(tid), "Oppdatering fra stedet.")
    requests = env.kartverket_requests()
    res = await env.cycle()
    assert (res.updated, res.geocoded) == (1, 1)
    assert env.kartverket_requests() == requests  # same lookups: answered from the cache


async def test_unplaced_event_is_regeocoded_on_update(env: Env) -> None:
    await env.cycle()
    tid = await env.scalar("SELECT id FROM events WHERE geom IS NULL ORDER BY id LIMIT 1")
    assert tid
    add_message(env.thread(tid), "Oppdatering.")
    res = await env.cycle()
    assert res.geocoded == 1


async def test_update_reclassifies_severity(env: Env) -> None:
    await env.cycle()
    tid = await env.scalar(
        "SELECT id FROM events WHERE severity = 'normal' AND category NOT IN ('Trafikk') ORDER BY id LIMIT 1"
    )
    assert tid
    add_message(env.thread(tid), "Det er meldt om en person med kniv.")
    await env.cycle()
    assert await env.scalar("SELECT severity FROM events WHERE id = :id", id=tid) == "severe"


# --- removed messages ----------------------------------------------------------------------------


async def thread_with_messages(env: Env, n: int) -> dict[str, Any]:
    return next(t for t in env.politi.threads if t["municipality"] == "Oslo" and len(t["messages"]) >= n)


async def seqs(env: Env, tid: str) -> list[int]:
    rows = await env.conn.execute(
        text("SELECT seq FROM event_messages WHERE event_id = :id ORDER BY seq"), {"id": tid}
    )
    return [r[0] for r in rows]


async def test_message_gone_from_thread_is_deleted(env: Env) -> None:
    await env.cycle()
    t = await thread_with_messages(env, 2)
    gone = t["messages"].pop(0)
    await env.cycle()
    assert int(gone["id"].rsplit("-", 1)[1]) not in await seqs(env, t["id"])
    assert len(await seqs(env, t["id"])) == len(t["messages"])


async def test_message_marked_removed_is_deleted(env: Env) -> None:
    await env.cycle()
    t = await thread_with_messages(env, 2)
    t["messages"][0]["type"] = "Removed"
    await env.cycle()
    assert len(await seqs(env, t["id"])) == len(t["messages"]) - 1


async def test_nothing_deleted_while_a_message_is_unparsed(env: Env, caplog) -> None:
    await env.cycle()
    t = await thread_with_messages(env, 2)
    before = await seqs(env, t["id"])
    t["messages"][0]["id"] = "garbage"
    with caplog.at_level(logging.WARNING):
        await env.cycle()
    assert await seqs(env, t["id"]) == before
    assert "stored messages kept" in caplog.text


async def test_edited_message_replaces_text(env: Env) -> None:
    await env.cycle()
    t = await thread_with_messages(env, 1)
    t["messages"][0]["text"] = "Rettet tekst."
    t["messages"][0]["type"] = "Edited"
    res = await env.cycle()
    assert res.updated == 1
    seq = int(t["messages"][0]["id"].rsplit("-", 1)[1])
    assert await env.scalar(
        "SELECT text FROM event_messages WHERE event_id = :id AND seq = :s", id=t["id"], s=seq
    ) == "Rettet tekst."  # fmt: skip


# --- failures ----------------------------------------------------------------------------------


async def test_failed_geocode_is_stored_unplaced_and_retried(env: Env) -> None:
    env.politi.threads = oslo_threads(5)
    env.kartverket_fail[0] = True
    res = await env.cycle()
    failed = res.geocode_failed  # threads with no lookups at all (no area, no street) don't fail
    assert res.ok and res.new == 5 and failed >= 3
    assert (
        await env.scalar("SELECT count(*) FROM events WHERE geocode_method IS NULL AND geom IS NULL")
        == failed
    )
    assert await env.scalar("SELECT count(*) FROM geocode_cache WHERE key NOT LIKE 'kommuner|%'") == 0

    env.kartverket_fail[0] = False
    env.now[0] += timedelta(minutes=1)
    res = await env.cycle()  # threads unchanged, but their geocode failed: retried
    assert (res.updated, res.unchanged, res.geocoded, res.geocode_failed) == (failed, 5 - failed, failed, 0)
    assert await env.scalar("SELECT count(*) FROM events WHERE geocode_method IS NULL") == 0

    res = await env.cycle()
    assert (res.unchanged, res.geocoded) == (5, 0)


async def test_politiloggen_backoff_then_failure_recorded(env: Env, caplog) -> None:
    env.politi.fail_with = 503
    with caplog.at_level(logging.WARNING):
        res = await env.cycle()
    assert not res.ok and "503" in (res.error or "")
    assert env.sleeps == [1.0, 2.0, 4.0, 8.0, 16.0]
    assert len(env.politi.calls) == 6
    assert await env.scalar("SELECT last_error_at FROM ingest_state") == env.now[0]
    assert await env.scalar("SELECT last_success_at FROM ingest_state") is None
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]  # not stale yet


async def test_stale_poll_logs_error(env: Env, caplog) -> None:
    assert (await env.cycle()).ok
    env.politi.fail_with = 429
    env.now[0] += timedelta(minutes=9)
    with caplog.at_level(logging.WARNING):
        await env.cycle()
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]

    env.now[0] += timedelta(minutes=1)
    caplog.clear()
    with caplog.at_level(logging.WARNING):
        await env.cycle()
    errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert len(errors) == 1 and "no successful Politiloggen poll for 10 min" in errors[0].getMessage()


async def test_stale_counts_from_start_when_never_successful(env: Env, caplog) -> None:
    env.politi.fail_with = 500
    env.now[0] += timedelta(minutes=11)
    with caplog.at_level(logging.ERROR):
        await env.cycle()
    assert "last success: never" in caplog.text


async def test_kommuneinfo_failure_fails_the_poll(env: Env) -> None:
    env.router.routes["kommuneinfo"].mock(return_value=httpx.Response(503))
    res = await env.cycle()
    assert not res.ok and await env.scalar("SELECT count(*) FROM events") == 0


async def test_one_bad_thread_is_rolled_back_alone(env: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    original = Geocoder.place
    calls = [0]

    async def place(self, area, text_):
        calls[0] += 1
        if calls[0] == 3:
            raise RuntimeError("boom")
        return await original(self, area, text_)

    monkeypatch.setattr(Geocoder, "place", place)
    res = await env.cycle()
    assert res.ok and res.errors == 1
    assert await env.scalar("SELECT count(*) FROM events") == N_OSLO - 1
    assert await env.scalar("SELECT count(*) FROM event_messages") == sum(
        len(t["messages"]) for t in oslo_threads()
    ) - len(by_last_message(oslo_threads())[2]["messages"])


async def test_clock_is_utc() -> None:
    assert parse_time("2026-11-12T10:00:00+01:00") == datetime(2026, 11, 12, 9, 0, tzinfo=UTC)
