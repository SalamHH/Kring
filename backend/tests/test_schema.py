"""Schema checks for migration 0001 (spec §8.4 + ingest_state)."""

from __future__ import annotations

import json
import uuid

import pytest
from alembic import command
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from tests.conftest import alembic_config

TABLES = {
    "events",
    "event_messages",
    "devices",
    "places",
    "notifications",
    "geocode_cache",
    "placement_feedback",
    "ingest_state",
}
OSLO = "SRID=4326;POINT(10.7522 59.9110)"


async def scalar(conn: AsyncConnection, sql: str, **params):
    return (await conn.execute(text(sql), params)).scalar()


async def assert_rejected(conn: AsyncConnection, sql: str, **params) -> None:
    """The statement must fail with an integrity error; a savepoint keeps the test transaction usable."""
    with pytest.raises(IntegrityError):
        async with conn.begin_nested():
            await conn.execute(text(sql), params)


async def insert_device(conn: AsyncConnection) -> uuid.UUID:
    device_id = uuid.uuid4()
    await conn.execute(text("INSERT INTO devices (id, secret_hash) VALUES (:id, 'x')"), {"id": device_id})
    return device_id


PLACE_SQL = """
    INSERT INTO places (id, device_id, label, template, center, radius_m, categories, time_window)
    VALUES (:id, :device_id, :label, :template, ST_GeogFromText(:center), :radius_m,
            :categories, CAST(:time_window AS jsonb))
"""


def place_params(device_id: uuid.UUID, **overrides) -> dict:
    params = {
        "id": uuid.uuid4(),
        "device_id": device_id,
        "label": "Skolen",
        "template": "skole",
        "center": OSLO,
        "radius_m": 1000,
        "categories": ["Vold", "Brann"],
        "time_window": json.dumps({"days": [1, 2, 3, 4, 5], "from": "08:00", "to": "16:00"}),
    }
    params.update(overrides)
    return params


EVENT_SQL = """
    INSERT INTO events (id, category, severity, first_message_at, last_message_at, raw)
    VALUES (:id, 'Brann', :severity, now(), now(), '{}'::jsonb)
"""


async def test_postgis_installed(db: AsyncConnection) -> None:
    assert await scalar(db, "SELECT extversion FROM pg_extension WHERE extname = 'postgis'")


async def test_all_tables_exist(db: AsyncConnection) -> None:
    rows = await db.execute(text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'"))
    assert TABLES <= {r[0] for r in rows}


@pytest.mark.parametrize(("index", "table"), [("events_geom_gix", "events"), ("places_center_gix", "places")])
async def test_gist_indexes(db: AsyncConnection, index: str, table: str) -> None:
    indexdef = await scalar(db, "SELECT indexdef FROM pg_indexes WHERE indexname = :i", i=index)
    assert indexdef is not None
    assert f"ON public.{table} USING gist" in indexdef


async def test_valid_place_is_accepted(db: AsyncConnection) -> None:
    device_id = await insert_device(db)
    await db.execute(text(PLACE_SQL), place_params(device_id))
    assert await scalar(db, "SELECT count(*) FROM places WHERE device_id = :d", d=device_id) == 1


@pytest.mark.parametrize("radius", [200, 299, 2001])
async def test_place_radius_out_of_range_rejected(db: AsyncConnection, radius: int) -> None:
    device_id = await insert_device(db)
    await assert_rejected(db, PLACE_SQL, **place_params(device_id, radius_m=radius))


@pytest.mark.parametrize("radius", [300, 2000])
async def test_place_radius_bounds_accepted(db: AsyncConnection, radius: int) -> None:
    device_id = await insert_device(db)
    await db.execute(text(PLACE_SQL), place_params(device_id, radius_m=radius))


async def test_place_label_over_40_chars_rejected(db: AsyncConnection) -> None:
    device_id = await insert_device(db)
    await db.execute(text(PLACE_SQL), place_params(device_id, label="x" * 40))
    await assert_rejected(db, PLACE_SQL, **place_params(device_id, label="x" * 41))


async def test_place_unknown_template_rejected(db: AsyncConnection) -> None:
    device_id = await insert_device(db)
    await assert_rejected(db, PLACE_SQL, **place_params(device_id, template="kontor"))


async def test_event_severity_must_be_known(db: AsyncConnection) -> None:
    await db.execute(text(EVENT_SQL), {"id": "ok-1", "severity": "severe"})
    await assert_rejected(db, EVENT_SQL, id="bad-1", severity="x")


async def test_notifications_unique_per_place_event_kind(db: AsyncConnection) -> None:
    device_id = await insert_device(db)
    params = place_params(device_id)
    await db.execute(text(PLACE_SQL), params)
    await db.execute(text(EVENT_SQL), {"id": "evt-1", "severity": "severe"})
    sql = "INSERT INTO notifications (place_id, event_id, kind) VALUES (:p, 'evt-1', :k)"
    await db.execute(text(sql), {"p": params["id"], "k": "push"})
    await db.execute(text(sql), {"p": params["id"], "k": "digest"})
    await assert_rejected(db, sql, p=params["id"], k="push")


async def test_ingest_state_is_single_row(db: AsyncConnection) -> None:
    await db.execute(text("INSERT INTO ingest_state DEFAULT VALUES"))
    await assert_rejected(db, "INSERT INTO ingest_state DEFAULT VALUES")
    await assert_rejected(db, "INSERT INTO ingest_state (id) VALUES (false)")


async def test_deleting_device_cascades_to_places(db: AsyncConnection) -> None:
    device_id = await insert_device(db)
    await db.execute(text(PLACE_SQL), place_params(device_id))
    await db.execute(text("DELETE FROM devices WHERE id = :d"), {"d": device_id})
    assert await scalar(db, "SELECT count(*) FROM places WHERE device_id = :d", d=device_id) == 0


def test_migration_round_trip(migrated_db: str) -> None:
    """downgrade base -> upgrade head works on a populated-schema database (runs last in this module)."""
    cfg = alembic_config(migrated_db)
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
