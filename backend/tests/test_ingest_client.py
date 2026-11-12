"""Politiloggen fetching: time window and the §8.3 paging stop rule (fake pages, no network)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.ingest.client import PollFailed, choose_time_span, fetch_window
from app.ingest.politiloggen import Page, Thread
from app.settings import Settings

NOW = datetime(2026, 11, 12, 12, 0, tzinfo=UTC)
S = Settings(page_size=2, min_pages=3, poll_safety_margin_s=900)


def thread(tid: str, minutes_ago: float) -> Thread:
    t = NOW - timedelta(minutes=minutes_ago)
    return Thread(tid, None, "Oslo", None, "Trafikk", t, t, True, (), raw={})


class FakeClient:
    def __init__(self, pages: list[list[Thread]], has_more_last: bool = False) -> None:
        self.pages = pages
        self.has_more_last = has_more_last
        self.calls: list[tuple[str, int, int]] = []

    async def fetch_page(self, time_span: str, skip: int, take: int) -> Page:
        self.calls.append((time_span, skip, take))
        i = len(self.calls) - 1
        if i >= len(self.pages):
            return Page([], has_more=False)
        more = i < len(self.pages) - 1 or self.has_more_last
        return Page(self.pages[i], has_more=more, size=len(self.pages[i]))


async def nosleep(_: float) -> None:
    pass


@pytest.mark.parametrize(
    "last_success, expected",
    [(None, "LastQuarter"), (NOW - timedelta(minutes=1), "LastDay"), (NOW - timedelta(hours=23), "LastDay"),
     (NOW - timedelta(hours=23, seconds=1), "LastQuarter")],
)  # fmt: skip
def test_time_span(last_success: datetime | None, expected: str) -> None:
    assert choose_time_span(S, last_success, NOW) == expected


async def test_reads_at_least_min_pages_even_if_old() -> None:
    old = [[thread(f"{p}{i}", 600) for i in range(2)] for p in "abcdef"]
    client = FakeClient(old)
    w = await fetch_window(client, S, NOW - timedelta(minutes=1), NOW, sleep=nosleep)  # type: ignore[arg-type]
    assert w.pages == 3
    assert [c[1] for c in client.calls] == [0, 2, 4]  # skip += len(page)


async def test_continues_while_a_page_has_recent_threads() -> None:
    last_success = NOW - timedelta(minutes=1)
    # pages 3 and 4 each have a thread inside the 15-min margin → read page 5, which is all old
    pages = [[thread(f"{p}{i}", 600) for i in range(2)] for p in "ab"]
    pages += [[thread("c0", 600), thread("c1", 5)]]
    pages += [[thread("d0", 10), thread("d1", 600)], [thread("e0", 600), thread("e1", 600)]]
    pages += [[thread("f0", 1), thread("f1", 1)]]
    client = FakeClient(pages)
    w = await fetch_window(client, S, last_success, NOW, sleep=nosleep)  # type: ignore[arg-type]
    assert w.pages == 5
    assert "f0" not in {t.id for t in w.threads}


async def test_margin_boundary() -> None:
    last_success = NOW - timedelta(minutes=1)
    # page 3: 14 min ago is inside last_success - 15 min → read page 4;
    # page 4: 16 min ago is outside → stop
    pages = [[thread(f"{p}{i}", 600) for i in range(2)] for p in "ab"]
    pages += [[thread("c0", 14)], [thread("d0", 16)], [thread("e0", 1)]]
    w = await fetch_window(FakeClient(pages), S, last_success, NOW, sleep=nosleep)  # type: ignore[arg-type]
    assert w.pages == 4


async def test_first_poll_reads_everything() -> None:
    pages = [[thread(f"{p}{i}", 6000) for i in range(2)] for p in "abcdefg"]
    w = await fetch_window(FakeClient(pages), S, None, NOW, sleep=nosleep)  # type: ignore[arg-type]
    assert w.pages == 7 and len(w.threads) == 14
    assert w.time_span == "LastQuarter"


async def test_stops_at_has_more_false_and_empty_page() -> None:
    w = await fetch_window(FakeClient([[thread("a", 1)]]), S, None, NOW, sleep=nosleep)  # type: ignore[arg-type]
    assert w.pages == 1
    client = FakeClient([[thread("a", 1), thread("b", 1)], []], has_more_last=True)
    w = await fetch_window(client, S, None, NOW, sleep=nosleep)  # type: ignore[arg-type]
    assert w.pages == 2


async def test_threads_are_deduplicated_across_pages() -> None:
    pages = [[thread("a", 1), thread("b", 1)], [thread("b", 1), thread("c", 1)]]
    w = await fetch_window(FakeClient(pages), S, None, NOW, sleep=nosleep)  # type: ignore[arg-type]
    assert [t.id for t in w.threads] == ["a", "b", "c"]


async def test_page_failure_propagates() -> None:
    class Failing(FakeClient):
        async def fetch_page(self, time_span: str, skip: int, take: int) -> Page:
            if skip:
                raise PollFailed("HTTP 503")
            return await super().fetch_page(time_span, skip, take)

    with pytest.raises(PollFailed):
        await fetch_window(Failing([[thread("a", 1)] * 2] * 3), S, None, NOW, sleep=nosleep)  # type: ignore[arg-type]
