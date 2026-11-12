"""Initial schema: spec §8.4 verbatim, plus ingest_state (decided 2026-11-12).

Revision ID: 0001
Revises:
Create Date: 2026-11-12
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# One statement per entry: asyncpg runs prepared statements, which cannot hold several commands.
UPGRADE: list[str] = [
    "CREATE EXTENSION IF NOT EXISTS postgis",
    """
    CREATE TABLE events (
      id               TEXT PRIMARY KEY,           -- Politiloggen thread id
      district         TEXT,
      municipality     TEXT,
      kommunenummer    TEXT,
      area             TEXT,
      category         TEXT NOT NULL,
      is_control       BOOLEAN NOT NULL DEFAULT false,
      severity         TEXT NOT NULL CHECK (severity IN ('severe','normal')),
      first_message_at TIMESTAMPTZ NOT NULL,
      last_message_at  TIMESTAMPTZ NOT NULL,
      is_active        BOOLEAN,
      geom             GEOGRAPHY(Point, 4326),
      uncertainty_m    INTEGER,
      precision_tier   TEXT CHECK (precision_tier IN ('gate','nabolag','bydel')),
      geocode_method   TEXT,   -- adresse|kryss|gate_area|gate_tekst|gate_omrade|stedsnavn|kommune
      geocode_match    TEXT,
      raw              JSONB NOT NULL,
      updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    "CREATE INDEX events_geom_gix  ON events USING GIST (geom)",
    "CREATE INDEX events_first_idx ON events (first_message_at DESC)",
    """
    CREATE TABLE event_messages (
      event_id   TEXT REFERENCES events(id) ON DELETE CASCADE,
      seq        INTEGER NOT NULL,
      created_at TIMESTAMPTZ NOT NULL,
      text       TEXT NOT NULL,
      PRIMARY KEY (event_id, seq)
    )
    """,
    """
    CREATE TABLE devices (
      id           UUID PRIMARY KEY,
      secret_hash  TEXT NOT NULL,          -- bearer secret, hashed
      push_token   TEXT,
      platform     TEXT CHECK (platform IN ('ios','android')),
      tz           TEXT NOT NULL DEFAULT 'Europe/Oslo',
      created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
      last_seen_at TIMESTAMPTZ
    )
    """,
    """
    CREATE TABLE places (
      id          UUID PRIMARY KEY,
      device_id   UUID NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
      label       TEXT NOT NULL CHECK (char_length(label) <= 40),
      template    TEXT NOT NULL CHECK (template IN ('skole','hjem','hytte','jobb','annet')),
      center      GEOGRAPHY(Point, 4326) NOT NULL,
      radius_m    INTEGER NOT NULL CHECK (radius_m BETWEEN 300 AND 2000),
      categories  TEXT[] NOT NULL,  -- app categories (Appendix B), not police categories
      time_window JSONB NOT NULL,   -- {"days":[1,2,3,4,5],"from":"08:00","to":"16:00"} | {"all":true}
      push        BOOLEAN NOT NULL DEFAULT true,
      created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    "CREATE INDEX places_center_gix ON places USING GIST (center)",
    """
    CREATE TABLE notifications (
      id         BIGSERIAL PRIMARY KEY,
      place_id   UUID REFERENCES places(id) ON DELETE CASCADE,
      event_id   TEXT REFERENCES events(id) ON DELETE CASCADE,
      kind       TEXT NOT NULL CHECK (kind IN ('push','digest')),
      sent_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
      ticket_id  TEXT,
      status     TEXT,
      UNIQUE (place_id, event_id, kind)       -- guarantees no duplicate pushes
    )
    """,
    """
    CREATE TABLE geocode_cache (
      key TEXT PRIMARY KEY, value JSONB, fetched_at TIMESTAMPTZ DEFAULT now()
    )
    """,
    """
    CREATE TABLE placement_feedback (
      event_id TEXT, place_id UUID, created_at TIMESTAMPTZ DEFAULT now()
    )
    """,
    """
    CREATE TABLE ingest_state (
      id              BOOLEAN PRIMARY KEY DEFAULT true CHECK (id),   -- single row
      last_success_at TIMESTAMPTZ,
      last_error_at   TIMESTAMPTZ,
      last_error      TEXT
    )
    """,
]

# Reverse dependency order. The postgis extension is left installed: other databases or
# objects may use it, and CREATE EXTENSION IF NOT EXISTS makes re-upgrading safe.
TABLES_DOWN = [
    "ingest_state",
    "placement_feedback",
    "geocode_cache",
    "notifications",
    "places",
    "devices",
    "event_messages",
    "events",
]


def upgrade() -> None:
    # exec_driver_sql: no bind-parameter parsing, so the spec's comments (e.g. {"all":true}) stay verbatim.
    bind = op.get_bind()
    for stmt in UPGRADE:
        bind.exec_driver_sql(stmt)


def downgrade() -> None:
    for table in TABLES_DOWN:
        op.execute(f"DROP TABLE {table}")
