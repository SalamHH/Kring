"""One ingestion cycle (spec §8.3): fetch the window, keep threads in scope, upsert events and
messages, geocode and classify, and record the poll in ingest_state.

Per thread:
- New → geocode, classify, insert.
- Unchanged (same fields and messages as stored) → nothing, unless its last geocode failed.
- Updated → store the new fields and messages, reclassify from the full text (decided
  2026-11-12), and re-geocode if the area or municipality changed, there is no point yet, or
  the tier is still bydel or nabolag. Never re-push (no push in M0).

Decided 2026-11-12:
- Stored messages that are no longer in the thread (removed by the police, or now of type
  Removed) are deleted, unless a message in the thread failed to parse that cycle.
- If a Kartverket lookup fails while placing an event, the event is stored without a point and
  with geocode_method NULL. Any event in the window with a NULL method is geocoded again next
  cycle, changed or not. Failed lookups are never cached.

The caller owns the transaction. Each thread runs in a savepoint, so one bad thread is logged
and rolled back without losing the rest of the cycle.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.classify.rules import is_control, precision_tier, round_uncertainty, severity
from app.geocode.cache import CachedKartverket, GeocodeCache
from app.geocode.kartverket import KartverketClient
from app.geocode.pipeline import Geocoder, Placement
from app.ingest.client import PolitiloggenClient, PollFailed, fetch_window
from app.ingest.kommuner import Kommune, KommuneinfoFailed, KommuneRegister, in_scope, load_register
from app.ingest.politiloggen import Thread
from app.settings import Settings

log = logging.getLogger(__name__)

STALE_AFTER = timedelta(minutes=10)
REGISTER_MAX_AGE = timedelta(hours=24)
IMPRECISE_TIERS = frozenset({"bydel", "nabolag"})


@dataclass
class CycleResult:
    ok: bool
    time_span: str | None = None
    pages: int = 0
    fetched: int = 0
    in_scope: int = 0
    new: int = 0
    updated: int = 0
    unchanged: int = 0
    geocoded: int = 0
    geocode_failed: int = 0
    errors: int = 0
    error: str | None = None


@dataclass(frozen=True)
class Stored:
    kommunenummer: str | None
    area: str | None
    fields: tuple[Any, ...]
    messages: dict[int, tuple[datetime, str]]
    has_point: bool
    tier: str | None
    method: str | None


def _fields(t: Thread) -> tuple[Any, ...]:
    return (
        t.district,
        t.municipality,
        t.area,
        t.category,
        t.first_message_at,
        t.last_message_at,
        t.is_active,
    )


def _messages(t: Thread) -> dict[int, tuple[datetime, str]]:
    return {m.seq: (m.created_at or t.first_message_at, m.text) for m in t.messages}


class Ingestor:
    def __init__(
        self,
        settings: Settings,
        politi: PolitiloggenClient,
        kartverket: KartverketClient,
        http: httpx.AsyncClient,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.settings = settings
        self.politi = politi
        self.kartverket = kartverket
        self.http = http  # for kommuneinfo
        self.clock = clock
        self.started_at = clock()
        self._register: KommuneRegister | None = None
        self._register_at: datetime | None = None

    # --- cycle ------------------------------------------------------------------------------

    async def run_cycle(self, conn: AsyncConnection) -> CycleResult:
        now = self.clock()
        last_success = await self._last_success(conn)
        try:
            register = await self._get_register(conn, now)
            window = await fetch_window(self.politi, self.settings, last_success, now)
        except (PollFailed, KommuneinfoFailed) as e:
            await self._record_failure(conn, now, str(e), last_success)
            return CycleResult(ok=False, error=str(e))

        res = CycleResult(
            ok=True, time_span=window.time_span, pages=window.pages, fetched=len(window.threads)
        )
        geo = CachedKartverket(self.kartverket, GeocodeCache(conn))
        scoped = in_scope(window.threads, register, self.settings.allowed_fylker)
        res.in_scope = len(scoped)
        for st in scoped:
            try:
                async with conn.begin_nested():
                    await self._process(conn, geo, st.thread, st.kommune, res)
            except Exception:
                res.errors += 1
                log.exception("ingest: thread %s failed, rolled back", st.thread.id)

        await conn.execute(
            text(
                """
                INSERT INTO ingest_state (id, last_success_at) VALUES (true, :now)
                ON CONFLICT (id) DO UPDATE SET last_success_at = EXCLUDED.last_success_at
                """
            ),
            {"now": now},
        )
        log.info(
            "ingest %s: %d pages, %d threads, %d in scope, %d new, %d updated, %d unchanged, "
            "%d geocoded (%d with failed lookups), %d errors, %d Kartverket requests",
            res.time_span, res.pages, res.fetched, res.in_scope, res.new, res.updated, res.unchanged,
            res.geocoded, res.geocode_failed, res.errors, self.kartverket.requests,
        )  # fmt: skip
        return res

    async def _get_register(self, conn: AsyncConnection, now: datetime) -> KommuneRegister:
        # Kept in memory so the WARN for an unknown municipality is logged once, not every cycle.
        if self._register is None or self._register_at is None or now - self._register_at > REGISTER_MAX_AGE:
            self._register = await load_register(conn, self.http, self.settings.kommuneinfo_url, now=now)
            self._register_at = now
        return self._register

    async def _last_success(self, conn: AsyncConnection) -> datetime | None:
        return (await conn.execute(text("SELECT last_success_at FROM ingest_state WHERE id"))).scalar()

    async def _record_failure(
        self, conn: AsyncConnection, now: datetime, error: str, last_success: datetime | None
    ) -> None:
        await conn.execute(
            text(
                """
                INSERT INTO ingest_state (id, last_error_at, last_error) VALUES (true, :now, :err)
                ON CONFLICT (id) DO UPDATE
                SET last_error_at = EXCLUDED.last_error_at, last_error = EXCLUDED.last_error
                """
            ),
            {"now": now, "err": error[:1000]},
        )
        since = last_success or self.started_at
        if now - since >= STALE_AFTER:
            log.error(
                "ingest: no successful Politiloggen poll for %d min (last success: %s): %s",
                (now - since).total_seconds() // 60,
                last_success.isoformat() if last_success else "never",
                error,
            )
        else:
            log.warning("ingest: poll failed: %s", error)

    # --- one thread ---------------------------------------------------------------------------

    async def _process(
        self, conn: AsyncConnection, geo: CachedKartverket, t: Thread, k: Kommune, res: CycleResult
    ) -> None:
        stored = await self._load(conn, t.id)
        if stored is None:
            res.new += 1
            regeocode = True
        elif (
            stored.fields == _fields(t)
            and stored.messages == _messages(t)
            and stored.kommunenummer == k.nummer
        ):
            if stored.method is not None:
                res.unchanged += 1
                return
            res.updated += 1  # retry a failed geocode
            regeocode = True
        else:
            res.updated += 1
            regeocode = (
                stored.area != t.area
                or stored.kommunenummer != k.nummer
                or not stored.has_point
                or stored.tier in IMPRECISE_TIERS
                or stored.method is None
            )

        placement: Placement | None = None
        failed = False
        if regeocode:
            before = geo.failures
            placement = await Geocoder(geo, k.nummer, k.navn).place(t.area, t.text)
            failed = geo.failures > before
            res.geocoded += 1
            if failed:
                res.geocode_failed += 1
                log.warning("ingest: thread %s stored unplaced, Kartverket lookups failed", t.id)
        await self._upsert_event(conn, t, k, placement if not failed else None, regeocode)
        await self._upsert_messages(conn, t)

    async def _load(self, conn: AsyncConnection, event_id: str) -> Stored | None:
        row = (
            await conn.execute(
                text(
                    """
                    SELECT kommunenummer, district, municipality, area, category, first_message_at,
                           last_message_at, is_active, geom IS NOT NULL, precision_tier, geocode_method
                    FROM events WHERE id = :id
                    """
                ),
                {"id": event_id},
            )
        ).first()
        if row is None:
            return None
        msgs = await conn.execute(
            text("SELECT seq, created_at, text FROM event_messages WHERE event_id = :id"), {"id": event_id}
        )
        return Stored(
            kommunenummer=row[0],
            area=row[3],
            fields=tuple(row[1:8]),
            messages={m[0]: (m[1], m[2]) for m in msgs},
            has_point=row[8],
            tier=row[9],
            method=row[10],
        )

    async def _upsert_event(
        self, conn: AsyncConnection, t: Thread, k: Kommune, p: Placement | None, set_geo: bool
    ) -> None:
        """Insert or update the event. Geo columns are written only when `set_geo`; then p=None
        means «geocoding failed»: no point, method NULL (retried next cycle)."""
        u = round_uncertainty(p.uncertainty_m) if p else None
        params = {
            "id": t.id, "district": t.district, "municipality": t.municipality, "knr": k.nummer,
            "area": t.area, "category": t.category, "is_control": is_control(t.category, t.text),
            "severity": severity(t.category, t.text), "first": t.first_message_at, "last": t.last_message_at,
            "active": t.is_active, "raw": json.dumps(t.raw, ensure_ascii=False),
            "lat": p.lat if p and p.has_point else None, "lon": p.lon if p and p.has_point else None,
            "u": u if p and p.has_point else None, "tier": precision_tier(u if p and p.has_point else None),
            "method": p.method if p else None, "match": p.match if p else None,
        }  # fmt: skip
        geo_update = (
            """,
              geom = EXCLUDED.geom, uncertainty_m = EXCLUDED.uncertainty_m,
              precision_tier = EXCLUDED.precision_tier, geocode_method = EXCLUDED.geocode_method,
              geocode_match = EXCLUDED.geocode_match"""
            if set_geo
            else ""
        )
        await conn.execute(
            text(
                f"""
                INSERT INTO events (id, district, municipality, kommunenummer, area, category, is_control,
                  severity, first_message_at, last_message_at, is_active, geom, uncertainty_m,
                  precision_tier, geocode_method, geocode_match, raw, updated_at)
                VALUES (:id, :district, :municipality, :knr, :area, :category, :is_control, :severity,
                  :first, :last, :active,
                  CASE WHEN CAST(:lat AS double precision) IS NULL THEN NULL
                       ELSE ST_SetSRID(ST_MakePoint(CAST(:lon AS double precision),
                                                    CAST(:lat AS double precision)), 4326)::geography END,
                  :u, :tier, :method, :match, CAST(:raw AS jsonb), now())
                ON CONFLICT (id) DO UPDATE SET
                  district = EXCLUDED.district, municipality = EXCLUDED.municipality,
                  kommunenummer = EXCLUDED.kommunenummer, area = EXCLUDED.area,
                  category = EXCLUDED.category, is_control = EXCLUDED.is_control,
                  severity = EXCLUDED.severity, first_message_at = EXCLUDED.first_message_at,
                  last_message_at = EXCLUDED.last_message_at, is_active = EXCLUDED.is_active,
                  raw = EXCLUDED.raw, updated_at = now(){geo_update}
                """
            ),
            params,
        )

    async def _upsert_messages(self, conn: AsyncConnection, t: Thread) -> None:
        msgs = _messages(t)
        for seq, (created_at, body) in msgs.items():
            await conn.execute(
                text(
                    """
                    INSERT INTO event_messages (event_id, seq, created_at, text)
                    VALUES (:id, :seq, :created, :text)
                    ON CONFLICT (event_id, seq) DO UPDATE
                    SET created_at = EXCLUDED.created_at, text = EXCLUDED.text
                    WHERE (event_messages.created_at, event_messages.text)
                          IS DISTINCT FROM (EXCLUDED.created_at, EXCLUDED.text)
                    """
                ),
                {"id": t.id, "seq": seq, "created": created_at, "text": body},
            )
        if t.unparsed_messages == 0:
            await conn.execute(
                text("DELETE FROM event_messages WHERE event_id = :id AND NOT (seq = ANY(:seqs))"),
                {"id": t.id, "seqs": list(msgs)},
            )
        else:
            log.warning(
                "ingest: thread %s has %d unparsed messages; stored messages kept", t.id, t.unparsed_messages
            )
