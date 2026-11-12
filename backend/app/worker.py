"""The ingestion worker (spec §8.1): `python -m app.worker`.

Runs one ingestion cycle (app.ingest.ingestor) every `poll_interval_s`, each in its own
transaction.

Decided 2026-11-12:
- Interval: cycles start every `poll_interval_s`, measured from the start of the previous
  cycle. A cycle that runs over is followed at once by the next, with no overlap and no
  catching up on missed starts.
- Shutdown (SIGINT/SIGTERM): the cycle in progress is aborted and its transaction rolled back;
  the next start redoes it.
- One worker per database: a session-level Postgres advisory lock is taken at startup and held
  for the worker's lifetime. A second worker logs an ERROR and exits with status 1.

A cycle that crashes (for example, the database is unreachable) is logged and the loop goes on.
Politiloggen failures are not crashes: the ingestor records them in ingest_state itself.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import signal
import sys
import time
from collections.abc import Awaitable, Callable
from typing import Protocol

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

from app.geocode.kartverket import KartverketClient
from app.ingest.client import PolitiloggenClient
from app.ingest.ingestor import CycleResult, Ingestor
from app.settings import Settings, get_settings

log = logging.getLogger("app.worker")  # not __main__ under `python -m`

# pg advisory lock key for "the stedSafe ingestion worker" (arbitrary, fixed).
LOCK_KEY = 0x57ED5AFE


class AlreadyRunning(Exception):
    """Another worker holds the advisory lock on this database."""


class Cycle(Protocol):
    async def run_cycle(self, conn: AsyncConnection) -> CycleResult: ...


async def _wait_or_stop(stop: asyncio.Event, delay: float) -> None:
    with contextlib.suppress(TimeoutError):
        await asyncio.wait_for(stop.wait(), delay)


class Worker:
    def __init__(
        self,
        engine: AsyncEngine,
        ingestor: Cycle,
        interval_s: float,
        *,
        monotonic: Callable[[], float] = time.monotonic,
        wait: Callable[[asyncio.Event, float], Awaitable[None]] = _wait_or_stop,
    ) -> None:
        self.engine = engine
        self.ingestor = ingestor
        self.interval_s = interval_s
        self._monotonic = monotonic
        self._wait = wait
        self.cycles = 0

    async def run_once(self) -> CycleResult:
        async with self.engine.begin() as conn:
            return await self.ingestor.run_cycle(conn)

    async def run(self, stop: asyncio.Event) -> None:
        """Loop until `stop` is set. Raises AlreadyRunning if another worker holds the lock."""
        async with self.engine.connect() as lock_conn:
            got = (await lock_conn.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": LOCK_KEY})).scalar()
            await lock_conn.commit()  # the lock is session-level; don't sit idle in a transaction
            if not got:
                raise AlreadyRunning("another worker holds the ingestion lock on this database")
            try:
                await self._loop(stop)
            finally:
                with contextlib.suppress(Exception):
                    await lock_conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": LOCK_KEY})
                    await lock_conn.commit()

    async def _loop(self, stop: asyncio.Event) -> None:
        log.info("worker: started, one cycle every %g s", self.interval_s)
        while not stop.is_set():
            started = self._monotonic()
            cycle = asyncio.create_task(self.run_once())
            stopped = asyncio.create_task(stop.wait())
            done, _ = await asyncio.wait({cycle, stopped}, return_when=asyncio.FIRST_COMPLETED)
            if cycle not in done:
                cycle.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await cycle
                log.info("worker: stopped during a cycle; it was rolled back")
                break
            stopped.cancel()
            self.cycles += 1
            try:
                cycle.result()
            except Exception:
                log.exception("worker: cycle crashed")
            remaining = self.interval_s - (self._monotonic() - started)
            if remaining > 0:
                await self._wait(stop, remaining)
        log.info("worker: stopped after %d cycles", self.cycles)


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )
    # One INFO line per HTTP request is too much at a 60 s poll with dozens of lookups.
    logging.getLogger("httpx").setLevel(logging.WARNING)


async def main(settings: Settings | None = None) -> int:
    settings = settings or get_settings()
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    try:
        async with httpx.AsyncClient() as http:
            ingestor = Ingestor(
                settings,
                PolitiloggenClient(http, settings.politiloggen_url),
                KartverketClient(http, settings.adresse_url, settings.stedsnavn_urls),
                http,
            )
            await Worker(engine, ingestor, settings.poll_interval_s).run(stop)
    except AlreadyRunning as e:
        log.error("worker: %s; exiting", e)
        return 1
    finally:
        await engine.dispose()
    return 0


if __name__ == "__main__":
    configure_logging()
    sys.exit(asyncio.run(main()))
