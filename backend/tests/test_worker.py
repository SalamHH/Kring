"""The worker loop: interval, shutdown mid-cycle, crash recovery and the one-worker lock.

Runs against the test database with a fake ingestor; the worker commits, so every test cleans
up the ingest_state row it may write.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Callable

import pytest
from sqlalchemy import pool, text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

from app.ingest.ingestor import CycleResult
from app.worker import AlreadyRunning, Worker


@pytest.fixture
async def engine(migrated_db: str) -> AsyncIterator[AsyncEngine]:
    eng = create_async_engine(migrated_db, poolclass=pool.NullPool)
    yield eng
    async with eng.begin() as conn:
        await conn.execute(text("DELETE FROM ingest_state"))
    await eng.dispose()


class FakeTime:
    """Fake monotonic clock. Waiting advances it; `stop_after` cycles, the wait sets stop."""

    def __init__(self, stop: asyncio.Event, stop_after: int) -> None:
        self.t = 0.0
        self.waits: list[float] = []
        self.stop = stop
        self.stop_after = stop_after
        self.cycles = 0

    def monotonic(self) -> float:
        return self.t

    async def wait(self, stop: asyncio.Event, delay: float) -> None:
        self.waits.append(round(delay, 6))
        self.t += delay
        if self.cycles >= self.stop_after:
            self.stop.set()


class FakeIngestor:
    """Each cycle advances fake time by the next duration and writes ingest_state."""

    def __init__(self, clock: FakeTime, durations: list[float],
                 on_cycle: Callable[[int], None] | None = None) -> None:  # fmt: skip
        self.clock = clock
        self.durations = durations
        self.on_cycle = on_cycle
        self.calls = 0

    async def run_cycle(self, conn: AsyncConnection) -> CycleResult:
        i = self.calls
        self.calls += 1
        await conn.execute(text("INSERT INTO ingest_state (id) VALUES (true) ON CONFLICT DO NOTHING"))
        await conn.execute(text("UPDATE ingest_state SET last_error = :e"), {"e": f"cycle {i}"})
        self.clock.t += self.durations[i]
        self.clock.cycles += 1
        if self.on_cycle:
            self.on_cycle(i)
        return CycleResult(ok=True)


async def stored_marker(engine: AsyncEngine) -> str | None:
    async with engine.connect() as conn:
        return (await conn.execute(text("SELECT last_error FROM ingest_state"))).scalar()


async def test_cycles_start_every_interval_and_overruns_go_at_once(engine: AsyncEngine) -> None:
    stop = asyncio.Event()
    clock = FakeTime(stop, stop_after=5)
    ing = FakeIngestor(clock, [5, 60, 75, 10, 1])
    worker = Worker(engine, ing, 60, monotonic=clock.monotonic, wait=clock.wait)
    await worker.run(stop)
    # 5 s → wait 55; exactly 60 → no wait; 75 → no wait, no catch-up; 10 → wait 50; 1 → wait 59
    assert clock.waits == [55, 50, 59]
    assert ing.calls == worker.cycles == 5
    assert await stored_marker(engine) == "cycle 4"  # every cycle committed


async def test_stop_between_cycles_returns_without_another_cycle(engine: AsyncEngine) -> None:
    stop = asyncio.Event()

    class Once:
        calls = 0

        async def run_cycle(self, conn: AsyncConnection) -> CycleResult:
            self.calls += 1
            asyncio.get_running_loop().call_later(0.05, stop.set)
            return CycleResult(ok=True)

    ing = Once()
    await asyncio.wait_for(Worker(engine, ing, 3600).run(stop), timeout=5)
    assert ing.calls == 1


async def test_stop_during_a_cycle_rolls_it_back(
    engine: AsyncEngine, caplog: pytest.LogCaptureFixture
) -> None:
    stop = asyncio.Event()
    entered = asyncio.Event()

    class Hangs:
        async def run_cycle(self, conn: AsyncConnection) -> CycleResult:
            await conn.execute(text("INSERT INTO ingest_state (id, last_error) VALUES (true, 'half')"))
            entered.set()
            await asyncio.sleep(3600)
            raise AssertionError("not reached")

    async def stopper() -> None:
        await entered.wait()
        stop.set()

    caplog.set_level(logging.INFO, logger="app.worker")
    await asyncio.wait_for(asyncio.gather(Worker(engine, Hangs(), 60).run(stop), stopper()), timeout=5)
    assert await stored_marker(engine) is None
    assert "rolled back" in caplog.text


async def test_a_crashed_cycle_is_logged_and_the_loop_goes_on(
    engine: AsyncEngine, caplog: pytest.LogCaptureFixture
) -> None:
    stop = asyncio.Event()
    clock = FakeTime(stop, stop_after=3)

    def boom(i: int) -> None:
        if i == 1:
            raise RuntimeError("database went away")

    ing = FakeIngestor(clock, [1, 1, 1], on_cycle=boom)
    await Worker(engine, ing, 60, monotonic=clock.monotonic, wait=clock.wait).run(stop)
    assert ing.calls == 3
    assert "cycle crashed" in caplog.text and "database went away" in caplog.text
    assert await stored_marker(engine) == "cycle 2"  # cycle 1 rolled back, 0 and 2 committed


async def test_only_one_worker_per_database(engine: AsyncEngine) -> None:
    stop = asyncio.Event()
    entered = asyncio.Event()

    class Waits:
        async def run_cycle(self, conn: AsyncConnection) -> CycleResult:
            entered.set()
            await stop.wait()
            return CycleResult(ok=True)

    first = asyncio.create_task(Worker(engine, Waits(), 60).run(stop))
    await asyncio.wait_for(entered.wait(), timeout=5)
    with pytest.raises(AlreadyRunning):
        await Worker(engine, Waits(), 60).run(asyncio.Event())
    stop.set()
    await asyncio.wait_for(first, timeout=5)

    # Released on exit: a new worker can start.
    stop2 = asyncio.Event()

    class Once:
        async def run_cycle(self, conn: AsyncConnection) -> CycleResult:
            stop2.set()
            return CycleResult(ok=True)

    await asyncio.wait_for(Worker(engine, Once(), 60).run(stop2), timeout=5)
