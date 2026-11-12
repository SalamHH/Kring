"""Politiloggen adapter (M0 step 6): recorded payloads, deliberately broken ones, and parity
with the reference script's `trad_til_rad`."""

from __future__ import annotations

import copy
import logging
from datetime import UTC, datetime
from typing import Any

import pytest

from app.ingest.politiloggen import Page, parse_page, parse_thread, parse_time
from tests.politiloggen_fixtures import page_sample, quarter
from tests.test_text_parity import ref


def thread(**overrides: Any) -> dict[str, Any]:
    t: dict[str, Any] = {
        "id": "26abc1",
        "district": "Oslo Politidistrikt",
        "districtId": 201,
        "category": "Trafikk",
        "municipality": "Oslo",
        "area": "Mosseveien V/ Ulvøya",
        "createdOn": "2026-11-12T10:00:00.1234567+00:00",
        "updatedOn": "2026-11-12T10:30:00+00:00",
        "lastMessageOn": "2026-11-12T10:30:00+00:00",
        "isActive": True,
        "messages": [
            {"id": "26abc1-0", "text": "Trafikkulykke.", "createdOn": "2026-11-12T10:00:00+00:00",
             "updatedOn": "2026-11-12T10:00:00+00:00", "type": "Published"},
            {"id": "26abc1-2", "text": "Veien er åpnet.", "createdOn": "2026-11-12T10:30:00+00:00",
             "updatedOn": "2026-11-12T10:31:00+00:00", "type": "Edited"},
        ],
    }  # fmt: skip
    t.update(overrides)
    return t


# --- recorded payloads -----------------------------------------------------------------------


def test_recorded_page_parses_completely() -> None:
    page = parse_page(page_sample())
    assert not page.malformed
    assert page.skipped == 0
    assert page.size == len(page_sample()["messageThreads"]) > 0
    assert len(page.threads) == page.size
    for t in page.threads:
        assert t.messages, t.id
        assert t.first_message_at <= t.last_message_at
        assert all(m.id == f"{t.id}-{m.seq}" for m in t.messages)


def test_recorded_quarter_parses_completely() -> None:
    page = parse_page({"messageThreads": quarter()["threads"], "hasMoreResults": False})
    assert page.skipped == 0
    assert len(page.threads) == len(quarter()["threads"])


def test_seq_comes_from_message_id_and_keeps_gaps() -> None:
    t = parse_thread(thread())
    assert t is not None
    assert [m.seq for m in t.messages] == [0, 2]
    assert t.messages[1].type == "Edited"


def test_first_message_at_is_earliest_message_not_thread_created() -> None:
    t = parse_thread(thread(createdOn="2026-11-12T09:00:00+00:00"))
    assert t is not None
    assert t.first_message_at == datetime(2026, 11, 12, 10, 0, tzinfo=UTC)
    assert t.last_message_at == datetime(2026, 11, 12, 10, 30, tzinfo=UTC)


def test_first_message_at_falls_back_to_thread_created() -> None:
    msgs = [{"id": "26abc1-0", "text": "Uten tid"}]
    t = parse_thread(thread(messages=msgs, lastMessageOn=None, updatedOn=None))
    assert t is not None
    assert t.first_message_at == t.last_message_at == datetime(2026, 11, 12, 10, 0, 0, 123456, tzinfo=UTC)


def test_field_lookup_ignores_case() -> None:
    raw = {k[0].upper() + k[1:]: v for k, v in thread().items()}
    t = parse_thread(raw)
    assert t is not None
    assert (t.id, t.municipality, t.area, len(t.messages)) == ("26abc1", "Oslo", "Mosseveien V/ Ulvøya", 2)


def test_hidden_message_types_are_dropped() -> None:
    msgs = thread()["messages"] + [
        {"id": "26abc1-3", "text": "utkast", "createdOn": "2026-11-12T10:40:00+00:00", "type": "Draft"},
        {"id": "26abc1-4", "text": "fjernet", "createdOn": "2026-11-12T10:41:00+00:00", "type": "Removed"},
    ]
    t = parse_thread(thread(messages=msgs))
    assert t is not None
    assert [m.seq for m in t.messages] == [0, 2]


@pytest.mark.parametrize(
    "value, expected",
    [
        ("2026-11-12T15:37:25.6356433+00:00", datetime(2026, 11, 12, 15, 37, 25, 635643, tzinfo=UTC)),
        ("2026-11-12T15:37:25Z", datetime(2026, 11, 12, 15, 37, 25, tzinfo=UTC)),
        ("2026-11-12T15:37:25", datetime(2026, 11, 12, 15, 37, 25, tzinfo=UTC)),
        ("i går", None),
        ("", None),
        (None, None),
        (1731424645, None),
    ],
)
def test_parse_time(value: Any, expected: datetime | None) -> None:
    assert parse_time(value) == expected


# --- broken payloads: never an exception -----------------------------------------------------

BROKEN_PAYLOADS: list[Any] = [
    None,
    [],
    "<html>Service Unavailable</html>",
    42,
    {},
    {"messageThreads": None},
    {"messageThreads": "nope", "hasMoreResults": True},
    {"messageThreads": {"id": "x"}},
    {"messageThreads": [None, 1, "x", [], {}], "hasMoreResults": "maybe"},
]


@pytest.mark.parametrize("payload", BROKEN_PAYLOADS, ids=range(len(BROKEN_PAYLOADS)))
def test_broken_payload_never_raises(payload: Any) -> None:
    page = parse_page(payload)
    assert isinstance(page, Page)
    assert page.threads == []
    assert page.has_more is False


def test_wrong_shape_is_flagged_malformed() -> None:
    assert parse_page(None).malformed
    assert parse_page({"messageThreads": "nope"}).malformed
    assert not parse_page({}).malformed  # an empty page is valid: stop paging


BROKEN_THREADS: list[tuple[str, dict[str, Any], bool]] = [
    # (what, overrides, parses)
    ("no id", {"id": None}, False),
    ("empty id", {"id": "  "}, False),
    ("id is an object", {"id": {"x": 1}}, False),
    ("no timestamps anywhere", {"createdOn": None, "updatedOn": None, "lastMessageOn": None,
                                "messages": [{"id": "26abc1-0", "text": "x"}]}, False),
    ("garbage timestamps", {"createdOn": "x", "updatedOn": 5, "lastMessageOn": [],
                            "messages": [{"id": "26abc1-0", "createdOn": "nei"}]}, False),
    ("messages missing", {"messages": None}, True),
    ("messages not a list", {"messages": "x"}, True),
    ("message items of wrong type", {"messages": [None, 3, "x", []]}, True),
    ("message with foreign id", {"messages": [{"id": "999-0", "text": "x"}]}, True),
    ("message without id", {"messages": [{"text": "x"}]}, True),
    ("message with non-numeric suffix", {"messages": [{"id": "26abc1-a", "text": "x"}]}, True),
    ("message text not a string", {"messages": [{"id": "26abc1-0", "text": {"a": 1}}]}, True),
    ("no category", {"category": None}, True),
    ("municipality is a number", {"municipality": 301}, True),
    ("isActive is a string", {"isActive": "yes"}, True),
    ("last before first", {"lastMessageOn": "2026-11-12T09:00:00+00:00"}, True),
]  # fmt: skip


@pytest.mark.parametrize("what, overrides, parses", BROKEN_THREADS, ids=[b[0] for b in BROKEN_THREADS])
def test_broken_thread(what: str, overrides: dict[str, Any], parses: bool, caplog) -> None:
    raw = thread(**overrides)
    with caplog.at_level(logging.WARNING):
        t = parse_thread(raw)
        page = parse_page({"messageThreads": [raw, thread(id="26ok00", messages=[])], "hasMoreResults": True})
    assert (t is not None) is parses
    assert [x.id for x in page.threads] == (["26abc1", "26ok00"] if parses else ["26ok00"])
    assert page.skipped == (0 if parses else 1)
    assert page.has_more is True
    if t is not None:
        assert t.first_message_at <= t.last_message_at
        assert t.category
        assert all(isinstance(m.text, str) for m in t.messages)


def test_duplicate_threads_in_a_page_are_kept_once() -> None:
    page = parse_page({"messageThreads": [thread(), thread(area="Annet")], "hasMoreResults": False})
    assert [t.area for t in page.threads] == ["Mosseveien V/ Ulvøya"]


def test_duplicate_message_seq_keeps_the_first() -> None:
    msgs = [{"id": "26abc1-0", "text": "a", "createdOn": "2026-11-12T10:00:00+00:00"},
            {"id": "26abc1-0", "text": "b", "createdOn": "2026-11-12T10:01:00+00:00"}]  # fmt: skip
    t = parse_thread(thread(messages=msgs))
    assert t is not None
    assert [m.text for m in t.messages] == ["a"]


def test_input_is_not_modified() -> None:
    raw = thread()
    before = copy.deepcopy(raw)
    t = parse_thread(raw)
    assert raw == before
    assert t is not None and t.raw is raw


# --- parity with the reference script --------------------------------------------------------


def all_recorded_threads() -> list[dict[str, Any]]:
    return page_sample()["messageThreads"] + quarter()["threads"]


def test_geocoder_inputs_match_trad_til_rad() -> None:
    """The area, municipality and joined text we hand the geocoder are what the script uses."""
    diffs = []
    for raw in all_recorded_threads():
        t = parse_thread(raw)
        assert t is not None
        rad = ref.trad_til_rad(raw)
        ours = (t.id, t.municipality, t.area, t.district, t.category, t.text)
        theirs = (rad["id"], rad["kommune"], rad["omrade"], rad["distrikt"], rad["kategori"], rad["tekst"])
        if ours != theirs:
            diffs.append((t.id, ours, theirs))
    assert diffs == []
