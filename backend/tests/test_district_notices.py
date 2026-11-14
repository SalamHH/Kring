"""District-wide notices (M1 step 2, spec §8.3, decided 2026-11-13): recorded notices from the
live feed, ingested next to the recorded Oslo threads."""

from __future__ import annotations

import copy
import logging
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import text

from app.geocode.text import norm
from app.ingest.ingestor import allowed_districts, district_kommuner
from app.regeocode import Filters, select_ids
from tests.politiloggen_fixtures import district_notices, register, scoped_raw_threads
from tests.test_ingestor import Env, add_message, env  # noqa: F401  (env is a fixture)


def notices_in(district: str) -> list[dict[str, Any]]:
    return [copy.deepcopy(t) for t in district_notices()["threads"] if norm(t["district"]) == norm(district)]


N_OSLO_NOTICES = len(notices_in("Oslo Politidistrikt"))
N_OTHER_NOTICES = len(district_notices()["threads"]) - N_OSLO_NOTICES


@pytest.fixture
def with_notices(env: Env) -> Env:  # noqa: F811
    env.politi.threads.extend(copy.deepcopy(district_notices()["threads"]))
    return env


def test_recording_has_oslo_and_ost_notices() -> None:
    assert N_OSLO_NOTICES >= 5
    assert notices_in("Øst Politidistrikt")
    assert all(t["area"] in ("", None) for t in district_notices()["threads"])


async def test_first_cycle_stores_notices_of_allowed_districts_only(
    with_notices: Env, caplog: pytest.LogCaptureFixture
) -> None:
    e = with_notices
    with caplog.at_level(logging.WARNING, logger="app.ingest.ingestor"):
        res = await e.cycle()
    assert res.ok and res.errors == 0
    # Settings allow Oslo only, so only Oslo politidistrikt covers an allowed fylke. It is known
    # from this same first cycle: notices are processed after the other threads.
    assert res.notices == N_OSLO_NOTICES
    assert res.notices_skipped == N_OTHER_NOTICES
    assert await e.scalar("SELECT count(*) FROM events WHERE scope = 'distrikt'") == N_OSLO_NOTICES
    assert await e.scalar(
        """SELECT count(*) FROM events WHERE scope = 'distrikt' AND (kommunenummer IS NOT NULL
           OR geom IS NOT NULL OR precision_tier IS NOT NULL OR geocode_method IS NOT NULL
           OR uncertainty_m IS NOT NULL)"""
    ) == 0  # fmt: skip
    assert await e.scalar("SELECT count(DISTINCT district) FROM events WHERE scope = 'distrikt'") == 1
    n_msgs = sum(len(t["messages"]) for t in notices_in("Oslo Politidistrikt"))
    assert await e.scalar(
        "SELECT count(*) FROM event_messages m JOIN events e ON e.id = m.event_id WHERE e.scope = 'distrikt'"
    ) == n_msgs  # fmt: skip
    # one WARN per skipped district, none for Oslo
    warned = [r.getMessage() for r in caplog.records if "covers no allowed fylke" in r.getMessage()]
    skipped_districts = {norm(t["district"]) for t in district_notices()["threads"]} - {"oslo politidistrikt"}
    assert len(warned) == len(skipped_districts)
    assert not any("Oslo" in w for w in warned)
    # ordinary events are unaffected
    sql = "SELECT count(*) FROM events WHERE scope = 'kommune' AND kommunenummer IS NULL"
    assert await e.scalar(sql) == 0


async def test_unchanged_notice_is_left_alone_and_no_new_warnings(
    with_notices: Env, caplog: pytest.LogCaptureFixture
) -> None:
    e = with_notices
    await e.cycle()
    updated_at = await e.scalar("SELECT max(updated_at) FROM events WHERE scope = 'distrikt'")
    e.now[0] += timedelta(minutes=1)
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="app.ingest.ingestor"):
        res = await e.cycle()
    assert res.notices == 0
    assert await e.scalar("SELECT max(updated_at) FROM events WHERE scope = 'distrikt'") == updated_at
    assert not [r for r in caplog.records if "covers no allowed fylke" in r.getMessage()]


async def test_notice_update_stores_new_message(with_notices: Env) -> None:
    e = with_notices
    await e.cycle()
    tid = notices_in("Oslo Politidistrikt")[0]["id"]
    add_message(e.thread(tid), "Personen er funnet i god behold.")
    e.now[0] += timedelta(minutes=10)
    res = await e.cycle()
    assert res.notices == 1
    assert await e.scalar(
        "SELECT text FROM event_messages WHERE event_id = :id ORDER BY seq DESC LIMIT 1", id=tid
    ) == "Personen er funnet i god behold."  # fmt: skip
    assert await e.scalar("SELECT geocode_method IS NULL AND geom IS NULL FROM events WHERE id = :id", id=tid)


async def test_regeocode_skips_notices(with_notices: Env) -> None:
    e = with_notices
    await e.cycle()
    ids = set(await select_ids(e.conn, Filters()))
    notice_ids = {t["id"] for t in notices_in("Oslo Politidistrikt")}
    assert not ids & notice_ids
    assert set(await select_ids(e.conn, Filters(ids=tuple(notice_ids)))) == set()


# --- the district map, from the recorded quarter ---------------------------------------------------

OSLO_DISTRICT = ["Oslo", "Bærum", "Asker"]
OST_DISTRICT = ["Lillestrøm", "Ullensaker", "Nordre Follo", "Lørenskog", "Eidsvoll", "Vestby", "Ås", "Nes",
                "Aurskog-Høland", "Frogn", "Nittedal", "Rælingen", "Enebakk", "Nannestad", "Nesodden",
                "Gjerdrum", "Hurdal"]  # fmt: skip


def knrs(names: list[str]) -> set[str]:
    reg = register()
    out = set()
    for n in names:
        k = reg.resolve(n)
        assert k is not None, n
        out.add(k.nummer)
    return out


async def test_district_map_from_recorded_quarter(db) -> None:
    for t, k in scoped_raw_threads():
        await db.execute(
            text(
                """INSERT INTO events (id, district, municipality, kommunenummer, category, severity,
                                       first_message_at, last_message_at, raw)
                   VALUES (:id, :d, :m, :k, :c, 'normal', now(), now(), '{}'::jsonb)"""
            ),
            {"id": t["id"], "d": t["district"], "m": t["municipality"], "k": k.nummer, "c": t["category"]},
        )
    m = await district_kommuner(db)
    assert m["oslo politidistrikt"] == knrs(OSLO_DISTRICT)
    assert m["øst politidistrikt"] == knrs(OST_DISTRICT)
    # Lunner and Jevnaker are in Akershus but in the Innlandet and Sør-Øst police districts
    assert m["innlandet politidistrikt"] == knrs(["Lunner"])
    assert m["sør-øst politidistrikt"] == knrs(["Jevnaker"])

    assert await allowed_districts(db, ["03"]) == {"oslo politidistrikt"}
    assert await allowed_districts(db, ["32"]) == {
        "oslo politidistrikt", "øst politidistrikt", "innlandet politidistrikt", "sør-øst politidistrikt",
    }  # fmt: skip
    assert await allowed_districts(db, ["46"]) == set()
