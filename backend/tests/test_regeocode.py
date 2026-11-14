"""Re-geocode command (M1 step 1, spec §9.6): recorded Oslo threads ingested into the test
database, then re-geocoded after a deliberate geocoder change."""

from __future__ import annotations

import io
import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import text

from app.geocode import pipeline
from app.geocode.cache import CachedKartverket, GeocodeCache
from app.geocode.pipeline import Geocoder
from app.ingest.politiloggen import parse_thread
from app.regeocode import (
    NO_METHOD,
    Filters,
    Report,
    compute,
    parse_args,
    print_report,
    regeocode,
    select_ids,
    write,
)
from tests.politiloggen_fixtures import register
from tests.test_ingestor import N_OSLO, Env, env  # noqa: F401  (env is a fixture)

# A deliberate geocoder change: «Sentrum» / «Oslo sentrum» at ±1 600 m instead of ±1 200 m. That
# moves its events from nabolag to bydel, and changes which streets are downgraded to the area.
WIDER_SENTRUM = {"lat": 59.9133, "lon": 10.7389, "usikkerhet_m": 1600.0,
                 "kilde": "stedsnavn", "detalj": "alias: Oslo sentrum"}  # fmt: skip


def widen_sentrum(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in (("0301", "sentrum"), ("0301", "oslo sentrum")):
        monkeypatch.setitem(pipeline.STED_ALIAS, key, WIDER_SENTRUM)


def geo(e: Env) -> CachedKartverket:
    return CachedKartverket(e.ingestor.kartverket, GeocodeCache(e.conn))


async def snapshot(e: Env) -> dict[str, tuple[Any, ...]]:
    rows = await e.conn.execute(
        text(
            """SELECT id, ST_AsText(geom), uncertainty_m, precision_tier, geocode_method, geocode_match,
                      is_control, severity, updated_at FROM events"""
        )
    )
    return {r[0]: tuple(r[1:]) for r in rows}


async def placements(e: Env) -> dict[str, tuple[Any, ...]]:
    """Each stored event placed directly by the geocoder, independently of the command."""
    g, reg = geo(e), register()
    out = {}
    rows = (await e.conn.execute(text("SELECT id, raw, municipality FROM events"))).all()
    for eid, raw, municipality in rows:
        t, k = parse_thread(json.loads(raw) if isinstance(raw, str) else raw), reg.resolve(municipality)
        assert t is not None and k is not None
        p = await Geocoder(g, k.nummer, k.navn).place(t.area, t.text)
        out[eid] = (p.method, p.match, p.uncertainty_m, p.lat, p.lon)
    return out


@pytest.fixture
async def stored(env: Env) -> Env:  # noqa: F811
    res = await env.cycle()
    assert res.ok and res.new == N_OSLO
    return env


async def test_no_geocoder_change_means_no_changes_and_no_requests(stored: Env) -> None:
    requests = stored.kartverket_requests()
    report = await regeocode(stored.conn, geo(stored), register())
    assert report.checked == N_OSLO
    assert report.unchanged == N_OSLO
    assert (report.changes, report.failed, report.unresolved) == ([], [], [])
    assert stored.kartverket_requests() == requests  # everything answered from the cache


async def test_dry_run_lists_exactly_the_changed_events_then_apply_writes_them(
    stored: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    before_placements = await placements(stored)
    widen_sentrum(monkeypatch)
    after_placements = await placements(stored)
    expected = {eid for eid in before_placements if before_placements[eid] != after_placements[eid]}
    assert expected, "the change should affect some recorded events"

    before = await snapshot(stored)
    dry = await regeocode(stored.conn, geo(stored), register())
    assert {c.id for c in dry.changes} == expected
    assert dry.unchanged == N_OSLO - len(expected)
    assert dry.applied == 0
    assert await snapshot(stored) == before  # a dry run writes nothing to events
    # every listed change is real: old = as stored, new = the wider alias
    for c in dry.changes:
        assert c.old != c.new
    assert any(c.new.uncertainty_m == 1600 and c.new.tier == "bydel" for c in dry.changes)

    applied = await regeocode(stored.conn, geo(stored), register(), apply=True)
    assert applied.applied == len(expected) and applied.skipped_busy == []
    after = await snapshot(stored)
    assert {eid for eid in after if after[eid] != before[eid]} == expected
    c = next(c for c in applied.changes if c.new.uncertainty_m == 1600)
    assert after[c.id][1:4] == (1600, "bydel", c.new.method)

    again = await regeocode(stored.conn, geo(stored), register())
    assert again.changes == [] and again.unchanged == N_OSLO


async def test_failed_lookup_keeps_old_placement_and_caches_nothing(stored: Env) -> None:
    await stored.conn.execute(text("DELETE FROM geocode_cache WHERE key LIKE 'sted4|%'"))
    stored.kartverket_fail[0] = True
    before = await snapshot(stored)

    report = await regeocode(stored.conn, geo(stored), register(), apply=True)
    assert report.failed, "events that need a place-name lookup should fail"
    assert report.applied == 0 and report.changes == []
    assert await snapshot(stored) == before
    assert await stored.scalar("SELECT count(*) FROM geocode_cache WHERE key LIKE 'sted4|%'") == 0


async def test_never_creates_notifications(stored: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    # A place right on top of an event the change will move, following every category.
    widen_sentrum(monkeypatch)
    dry = await regeocode(stored.conn, geo(stored), register())
    target = next(c for c in dry.changes if c.new.lat is not None)
    device = uuid.uuid4()
    await stored.conn.execute(text("INSERT INTO devices (id, secret_hash) VALUES (:d, 'x')"), {"d": device})
    await stored.conn.execute(
        text(
            """INSERT INTO places (id, device_id, label, template, center, radius_m, categories, time_window)
               VALUES (:p, :d, 'Test', 'annet', ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography, 2000,
                       ARRAY['Vold','Brann','Savnet','Ro og orden','Innbrudd','Tyveri','Trafikk','Andre'],
                       '{"all": true}')"""
        ),
        {"p": uuid.uuid4(), "d": device, "lat": target.new.lat, "lon": target.new.lon},
    )
    report = await regeocode(stored.conn, geo(stored), register(), apply=True)
    assert report.applied > 0
    assert await stored.scalar("SELECT count(*) FROM notifications") == 0


async def test_event_changed_by_worker_meanwhile_is_skipped(
    stored: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    widen_sentrum(monkeypatch)
    report = await regeocode(stored.conn, geo(stored), register())
    changes = report.changes
    assert len(changes) >= 2
    busy = changes[0].id
    # the worker updates this event between the command's read and its write
    await stored.conn.execute(
        text("UPDATE events SET updated_at = updated_at + interval '1 second' WHERE id = :id"), {"id": busy}
    )
    before = await snapshot(stored)

    await write(stored.conn, changes, report)
    assert report.skipped_busy == [busy]
    assert report.applied == len(changes) - 1
    assert (await snapshot(stored))[busy] == before[busy]


async def test_compute_reports_events_that_no_longer_resolve(stored: Env) -> None:
    eid = await stored.scalar("SELECT id FROM events ORDER BY id LIMIT 1")
    await stored.conn.execute(
        text("UPDATE events SET municipality = 'Ukjent kommune' WHERE id = :id"), {"id": eid}
    )
    report = await regeocode(stored.conn, geo(stored), register(), Filters(ids=(eid,)))
    assert report.unresolved == [eid] and report.changes == []


async def test_filters(stored: Env) -> None:
    conn = stored.conn
    all_ids = await select_ids(conn, Filters())
    assert len(all_ids) == N_OSLO and all_ids == sorted(all_ids)
    assert await select_ids(conn, Filters(kommuner=("3201",))) == []
    assert len(await select_ids(conn, Filters(kommuner=("0301",)))) == N_OSLO

    sample = all_ids[:3]
    assert await select_ids(conn, Filters(ids=tuple(sample))) == sample

    await conn.execute(text("UPDATE events SET geocode_method = NULL WHERE id = :id"), {"id": sample[0]})
    assert await select_ids(conn, Filters(methods=(NO_METHOD,))) == [sample[0]]
    n_kommune = await stored.scalar("SELECT count(*) FROM events WHERE geocode_method = 'kommune'")
    assert len(await select_ids(conn, Filters(methods=("kommune", NO_METHOD)))) == n_kommune + 1

    newest = await stored.scalar("SELECT max(first_message_at) FROM events")
    assert len(await select_ids(conn, Filters(since=newest))) >= 1
    assert await select_ids(conn, Filters(since=newest + timedelta(seconds=1))) == []


async def test_compute_batches_add_up(stored: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    widen_sentrum(monkeypatch)
    whole = await regeocode(stored.conn, geo(stored), register())
    report = Report()
    ids = await select_ids(stored.conn, Filters())
    for i in range(0, len(ids), 7):
        await compute(stored.conn, geo(stored), register(), ids[i : i + 7], report)
    assert report.checked == whole.checked
    assert [c.id for c in report.changes] == [c.id for c in whole.changes]


async def test_report_output(stored: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    widen_sentrum(monkeypatch)
    report = await regeocode(stored.conn, geo(stored), register())
    out = io.StringIO()
    print_report(report, apply=False, out=out)
    s = out.getvalue()
    assert report.changes[0].id in s
    assert "nabolag → bydel" in s
    assert f"{len(report.changes)} changed" in s
    assert "Dry run: nothing written" in s


def test_parse_args() -> None:
    a = parse_args([])
    assert not a.apply and a.since is None and a.kommune == () and a.method == () and a.ids == ()
    a = parse_args(
        ["--apply", "--since", "2026-11-01", "--kommune", "0301, 3201",
         "--method", "stedsnavn,none", "--ids", "abc"]
    )  # fmt: skip
    assert a.apply
    assert a.since == datetime(2026, 11, 1, tzinfo=UTC)
    assert a.kommune == ("0301", "3201") and a.method == ("stedsnavn", "none") and a.ids == ("abc",)
    assert parse_args(["--since", "2026-11-01T12:00:00+01:00"]).since == datetime(2026, 11, 1, 11, tzinfo=UTC)
