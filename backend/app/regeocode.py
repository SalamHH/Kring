"""Re-geocode stored events after a geocoder change (spec §9.6): `python -m app.regeocode`.

Stored events keep their placement until their thread changes, so a change to the geocoder
(a ranking, an alias, a new rule) doesn't reach events already in the database. This command
runs the geocoder and classifier again over stored events, from the thread as last ingested
(`events.raw`), and through the geocode cache.

- Dry run by default: prints what would change. `--apply` writes the changes.
- Filters: `--since`, `--kommune`, `--method`, `--ids`.
- It never pushes and never writes `notifications` (decided 2026-11-13). Events that start to
  match a place because of a new placement are not pushed later either: push only happens
  when the worker first stores an event (§8.7).
- A failed Kartverket lookup keeps the event's old placement; nothing is cached (§9.4).
- A dry run writes nothing to `events`, but successful lookups are cached as usual, so the
  `--apply` run that follows doesn't repeat them.

It runs safely alongside the worker (decided 2026-11-14). Placements are computed without
locks, then each batch is written in a short transaction that locks its rows with SKIP LOCKED
and writes only rows whose `updated_at` hasn't moved since they were read. An event that the
worker updated, or is updating, in between is reported as skipped; run the command again to
pick it up. The command never waits on the worker, and the worker waits on it only for the
few milliseconds of a batch write.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time
from typing import Any, TextIO

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

from app.classify.rules import is_control, precision_tier, round_uncertainty, severity
from app.geocode.cache import CachedKartverket, GeocodeCache
from app.geocode.kartverket import KartverketClient
from app.geocode.pipeline import Geocoder
from app.ingest.kommuner import KommuneRegister, load_register
from app.ingest.politiloggen import parse_thread
from app.settings import Settings, get_settings

log = logging.getLogger("app.regeocode")

BATCH_SIZE = 100
COORD_DECIMALS = 7  # ~1 cm; differences below this are noise from the geography round trip
NO_METHOD = "none"  # --method value for events whose last geocode failed (method NULL)


@dataclass(frozen=True)
class Filters:
    since: datetime | None = None  # first_message_at >= since
    kommuner: tuple[str, ...] = ()
    methods: tuple[str, ...] = ()  # NO_METHOD selects geocode_method IS NULL
    ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class Geo:
    """The geocode and classification columns of one event, as stored or as computed."""

    lat: float | None
    lon: float | None
    uncertainty_m: int | None
    tier: str | None
    method: str | None
    match: str | None
    is_control: bool
    severity: str

    def key(self) -> tuple[Any, ...]:
        r = COORD_DECIMALS
        return (
            None if self.lat is None else round(self.lat, r),
            None if self.lon is None else round(self.lon, r),
            self.uncertainty_m, self.tier, self.method, self.match, self.is_control, self.severity,
        )  # fmt: skip


@dataclass(frozen=True)
class Change:
    id: str
    kommunenummer: str
    updated_at: datetime
    old: Geo
    new: Geo


@dataclass
class Report:
    checked: int = 0
    unchanged: int = 0
    changes: list[Change] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)  # Kartverket lookups failed; old placement kept
    unresolved: list[str] = field(default_factory=list)  # raw thread or municipality no longer resolves
    applied: int = 0
    skipped_busy: list[str] = field(default_factory=list)  # changed or locked by the worker meanwhile


# --- reading ------------------------------------------------------------------------------------

_SELECT = """
    SELECT id, kommunenummer, municipality, category, raw, updated_at,
           ST_Y(geom::geometry), ST_X(geom::geometry), uncertainty_m, precision_tier,
           geocode_method, geocode_match, is_control, severity
    FROM events
"""


async def select_ids(conn: AsyncConnection, f: Filters) -> list[str]:
    where = ["kommunenummer IS NOT NULL"]
    params: dict[str, Any] = {}
    if f.since is not None:
        where.append("first_message_at >= :since")
        params["since"] = f.since
    if f.kommuner:
        where.append("kommunenummer = ANY(:kommuner)")
        params["kommuner"] = list(f.kommuner)
    if f.methods:
        named = [m for m in f.methods if m != NO_METHOD]
        parts = ["geocode_method = ANY(:methods)"] if named else []
        if NO_METHOD in f.methods:
            parts.append("geocode_method IS NULL")
        where.append("(" + " OR ".join(parts) + ")")
        params["methods"] = named
    if f.ids:
        where.append("id = ANY(:ids)")
        params["ids"] = list(f.ids)
    sql = f"SELECT id FROM events WHERE {' AND '.join(where)} ORDER BY id"
    return list((await conn.execute(text(sql), params)).scalars())


# --- computing ----------------------------------------------------------------------------------


async def compute(
    conn: AsyncConnection,
    geo: CachedKartverket,
    register: KommuneRegister,
    ids: Sequence[str],
    report: Report,
) -> list[Change]:
    """Re-geocode and reclassify `ids`; return the events whose stored columns would change."""
    rows = (await conn.execute(text(_SELECT + " WHERE id = ANY(:ids) ORDER BY id"), {"ids": list(ids)})).all()
    changes: list[Change] = []
    for row in rows:
        (eid, knr, municipality, category, raw, updated_at,
         lat, lon, u, tier, method, match, control, sev) = row  # fmt: skip
        report.checked += 1
        old = Geo(lat, lon, u, tier, method, match, control, sev)
        thread = parse_thread(json.loads(raw) if isinstance(raw, str) else raw)
        kommune = register.resolve(municipality)
        if thread is None or kommune is None or kommune.nummer != knr:
            report.unresolved.append(eid)
            log.warning("regeocode: %s: thread or municipality %r no longer resolves", eid, municipality)
            continue

        before = geo.failures
        p = await Geocoder(geo, kommune.nummer, kommune.navn).place(thread.area, thread.text)
        if geo.failures > before:
            report.failed.append(eid)
            continue

        u_new = round_uncertainty(p.uncertainty_m) if p.has_point else None
        new = Geo(
            lat=p.lat if p.has_point else None,
            lon=p.lon if p.has_point else None,
            uncertainty_m=u_new,
            tier=precision_tier(u_new),
            method=p.method,
            match=p.match,
            is_control=is_control(category, thread.text),
            severity=severity(category, thread.text),
        )
        if new.key() == old.key():
            report.unchanged += 1
        else:
            changes.append(Change(eid, knr, updated_at, old, new))
    report.changes.extend(changes)
    return changes


# --- writing ------------------------------------------------------------------------------------


async def write(conn: AsyncConnection, changes: Sequence[Change], report: Report) -> None:
    """Write `changes` in the caller's (short) transaction. Rows the worker holds a lock on,
    or has updated since they were read, are skipped and reported."""
    if not changes:
        return
    locked = dict(
        (
            await conn.execute(
                text(
                    "SELECT id, updated_at FROM events WHERE id = ANY(:ids) "
                    "ORDER BY id FOR UPDATE SKIP LOCKED"
                ),
                {"ids": [c.id for c in changes]},
            )
        ).all()
    )
    for c in changes:
        if locked.get(c.id) != c.updated_at:
            report.skipped_busy.append(c.id)
            continue
        n = c.new
        await conn.execute(
            text(
                """
                UPDATE events SET
                  geom = CASE WHEN CAST(:lat AS double precision) IS NULL THEN NULL
                    ELSE ST_SetSRID(ST_MakePoint(CAST(:lon AS double precision),
                                                 CAST(:lat AS double precision)), 4326)::geography END,
                  uncertainty_m = :u, precision_tier = :tier, geocode_method = :method,
                  geocode_match = :match, is_control = :is_control, severity = :severity,
                  updated_at = now()
                WHERE id = :id
                """
            ),
            {"id": c.id, "lat": n.lat, "lon": n.lon, "u": n.uncertainty_m, "tier": n.tier,
             "method": n.method, "match": n.match, "is_control": n.is_control, "severity": n.severity},
        )  # fmt: skip
        report.applied += 1


# --- one connection (tests) and the batched CLI run ---------------------------------------------


async def regeocode(
    conn: AsyncConnection,
    geo: CachedKartverket,
    register: KommuneRegister,
    filters: Filters | None = None,
    *,
    apply: bool = False,
) -> Report:
    """The whole run on one connection, in the caller's transaction."""
    report = Report()
    changes = await compute(conn, geo, register, await select_ids(conn, filters or Filters()), report)
    if apply:
        await write(conn, changes, report)
    return report


def _batches(ids: Sequence[str], size: int) -> Iterable[Sequence[str]]:
    for i in range(0, len(ids), size):
        yield ids[i : i + size]


async def run(
    engine: AsyncEngine,
    http: httpx.AsyncClient,
    settings: Settings,
    filters: Filters,
    *,
    apply: bool,
    batch_size: int = BATCH_SIZE,
) -> Report:
    """Batched run: each batch is computed in one transaction (committing its cache writes),
    then, with `apply`, written in a second, short one."""
    async with engine.begin() as conn:
        ids = await select_ids(conn, filters)
        register = await load_register(conn, http, settings.kommuneinfo_url)
    log.info("regeocode: %d events selected (%s)", len(ids), "apply" if apply else "dry run")
    client = KartverketClient(http, settings.adresse_url, settings.stedsnavn_urls)
    report = Report()
    for batch in _batches(ids, batch_size):
        async with engine.begin() as conn:
            geo = CachedKartverket(client, GeocodeCache(conn))
            changes = await compute(conn, geo, register, batch, report)
        if apply and changes:
            async with engine.begin() as conn:
                await write(conn, changes, report)
        log.info("regeocode: %d/%d checked, %d changes", report.checked, len(ids), len(report.changes))
    return report


# --- output -------------------------------------------------------------------------------------


def _fmt(g: Geo) -> str:
    u = "-" if g.uncertainty_m is None else f"±{g.uncertainty_m} m"
    return f"{g.method or 'NULL'} {u} {g.tier or '-'} «{g.match or ''}»"


def _flags(c: Change) -> str:
    out = []
    if c.old.is_control != c.new.is_control:
        out.append(f"control {c.old.is_control}→{c.new.is_control}")
    if c.old.severity != c.new.severity:
        out.append(f"severity {c.old.severity}→{c.new.severity}")
    return f"  [{', '.join(out)}]" if out else ""


def print_report(report: Report, *, apply: bool, out: TextIO = sys.stdout) -> None:
    w = out.write
    for c in report.changes:
        w(f"{c.id}  {c.kommunenummer}  {_fmt(c.old)}  →  {_fmt(c.new)}{_flags(c)}\n")
    if report.changes:
        tiers = Counter((c.old.tier, c.new.tier) for c in report.changes if c.old.tier != c.new.tier)
        if tiers:
            w("\nTier changes:\n")
            for (a, b), n in sorted(tiers.items(), key=lambda kv: (-kv[1], str(kv[0]))):
                w(f"  {a} → {b}: {n}\n")
        methods = Counter(
            (c.old.method, c.new.method) for c in report.changes if c.old.method != c.new.method
        )
        if methods:
            w("Method changes:\n")
            for (a, b), n in sorted(methods.items(), key=lambda kv: (-kv[1], str(kv[0]))):
                w(f"  {a} → {b}: {n}\n")
    w(
        f"\n{report.checked} checked, {report.unchanged} unchanged, {len(report.changes)} changed, "
        f"{len(report.failed)} kept after failed Kartverket lookups, "
        f"{len(report.unresolved)} kept (no longer resolve).\n"
    )
    if apply:
        w(f"Applied {report.applied}; skipped {len(report.skipped_busy)} the worker changed meanwhile")
        w(" (run again to pick them up).\n" if report.skipped_busy else ".\n")
    elif report.changes:
        w("Dry run: nothing written to events. Run again with --apply to write these changes.\n")


# --- CLI ----------------------------------------------------------------------------------------


def _since(value: str) -> datetime:
    """An ISO date (midnight UTC) or an ISO timestamp (UTC if no offset)."""
    try:
        d = datetime.fromisoformat(value)
    except ValueError:
        d = datetime.combine(date.fromisoformat(value), time())
    return d if d.tzinfo else d.replace(tzinfo=UTC)


def _csv(value: str) -> tuple[str, ...]:
    return tuple(v.strip() for v in value.split(",") if v.strip())


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        prog="python -m app.regeocode",
        description="Re-geocode and reclassify stored events (spec §9.6). Dry run unless --apply.",
    )
    ap.add_argument("--apply", action="store_true", help="write the changes (default: dry run)")
    ap.add_argument("--since", type=_since, help="only events whose first message is at or after this "
                    "ISO date or timestamp (UTC unless an offset is given)")  # fmt: skip
    ap.add_argument("--kommune", type=_csv, default=(), help="comma-separated kommunenummer, e.g. 0301,3201")
    ap.add_argument("--method", type=_csv, default=(),
                    help=f"comma-separated geocode_method; '{NO_METHOD}' = geocode failed")  # fmt: skip
    ap.add_argument("--ids", type=_csv, default=(), help="comma-separated event (thread) ids")
    ap.add_argument("--batch-size", type=int, default=BATCH_SIZE)
    return ap.parse_args(argv)


async def main(argv: Sequence[str] | None = None, settings: Settings | None = None) -> int:
    args = parse_args(argv)
    settings = settings or get_settings()
    filters = Filters(since=args.since, kommuner=args.kommune, methods=args.method, ids=args.ids)
    engine = create_async_engine(settings.database_url)
    try:
        async with httpx.AsyncClient() as http:
            report = await run(engine, http, settings, filters, apply=args.apply, batch_size=args.batch_size)
    finally:
        await engine.dispose()
    print_report(report, apply=args.apply)
    return 0


if __name__ == "__main__":
    from app.worker import configure_logging

    configure_logging()
    sys.exit(asyncio.run(main()))
