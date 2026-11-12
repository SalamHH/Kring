"""Typed adapter for the Politiloggen `/messagethreads` payload (spec §8.3).

The field names are not officially documented. They were checked against the API's Swagger
spec (`/swagger/v1/swagger.json`, MessageThreadDto / ThreadMessageDto) and a live sample on
2026-11-12, but every lookup still goes through `pick()` (case-insensitive, several candidate
names) so a renamed or missing field degrades to a skipped thread or message, never a crash.

Message identity (decided 2026-11-12): a message id is `<threadId>-<n>`, and `n` is stored as
`event_messages.seq`. Gaps in `n` are normal (removed messages). A message whose id does not
follow that pattern is skipped with a WARN. An «Edited» message keeps its seq; its new text
replaces the old one on upsert.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.ingest.fields import pick

log = logging.getLogger(__name__)

# Candidate field names, checked case-insensitively. The first name is the one seen live.
F_THREADS = ("messageThreads", "threads", "items")
F_HAS_MORE = ("hasMoreResults", "hasMore")
F_ID = ("id", "threadId", "messageThreadId")
F_DISTRICT = ("district", "districtName", "policeDistrict")
F_MUNICIPALITY = ("municipality", "municipalityName", "kommune")
F_AREA = ("area", "areaName", "place", "location")
F_CATEGORY = ("category", "categoryName", "type")
F_CREATED = ("createdOn", "createdAt", "startedOn", "firstMessageOn")
F_LAST_MESSAGE = ("lastMessageOn", "lastMessageAt", "updatedOn")
F_ACTIVE = ("isActive", "active")
F_MESSAGES = ("messages", "updates", "messageList")
F_MSG_ID = ("id", "messageId")
F_MSG_TEXT = ("text", "message", "body", "content")
F_MSG_CREATED = ("createdOn", "createdAt")
F_MSG_UPDATED = ("updatedOn", "updatedAt")
F_MSG_TYPE = ("type", "messageType")

UNKNOWN_CATEGORY = "Ukjent"  # as in the reference script
# Swagger MessageTypeEnum: Draft, Published, Edited, Removed. Only public ones are kept.
HIDDEN_MESSAGE_TYPES = frozenset({"draft", "removed"})


@dataclass(frozen=True)
class Message:
    seq: int
    id: str
    text: str
    created_at: datetime | None
    updated_at: datetime | None
    type: str | None


@dataclass(frozen=True)
class Thread:
    id: str
    district: str | None
    municipality: str | None
    area: str | None
    category: str
    first_message_at: datetime
    last_message_at: datetime
    is_active: bool | None
    messages: tuple[Message, ...]
    raw: dict[str, Any] = field(repr=False, compare=False)
    # Messages that could not be parsed (not counting Draft/Removed, which are dropped on
    # purpose). While this is > 0 the ingestor deletes no stored messages for the thread.
    unparsed_messages: int = 0

    @property
    def text(self) -> str:
        """All message texts joined with spaces, the geocoder input (as `trad_til_rad`)."""
        return " ".join(m.text for m in self.messages).strip()


@dataclass(frozen=True)
class Page:
    threads: list[Thread]
    has_more: bool
    skipped: int = 0  # threads in the payload that could not be parsed
    malformed: bool = False  # the payload itself was not the expected shape
    size: int = 0  # raw threads in the payload, parsed or not (for `skip +=`)


def parse_time(value: Any) -> datetime | None:
    """ISO 8601 → aware datetime (UTC if no offset is given), or None if unusable.
    The API sends 7 fractional digits; Python 3.12 truncates beyond 6."""
    if not isinstance(value, str) or not value.strip():
        return None
    s = value.strip()
    if s.endswith(("Z", "z")):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _str(value: Any) -> str | None:
    if value is None or isinstance(value, (dict, list)):
        return None
    s = str(value).strip()
    return s or None


def _bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.lower() in ("true", "false"):
        return value.lower() == "true"
    return None


def _is_hidden(raw: Any) -> bool:
    mtype = _str(pick(raw, F_MSG_TYPE)) if isinstance(raw, dict) else None
    return bool(mtype) and mtype.lower() in HIDDEN_MESSAGE_TYPES


def parse_message(raw: Any, thread_id: str) -> Message | None:
    if not isinstance(raw, dict):
        log.warning("Politiloggen thread %s: message is not an object, skipped", thread_id)
        return None
    if _is_hidden(raw):
        return None
    mid = _str(pick(raw, F_MSG_ID))
    m = re.fullmatch(re.escape(thread_id) + r"-(\d+)", mid or "")
    if not m:
        log.warning("Politiloggen thread %s: message id %r is not <thread>-<n>, skipped", thread_id, mid)
        return None
    mtype = _str(pick(raw, F_MSG_TYPE))
    text = pick(raw, F_MSG_TEXT)
    return Message(
        seq=int(m.group(1)),
        id=mid or "",
        text=text if isinstance(text, str) else "",
        created_at=parse_time(pick(raw, F_MSG_CREATED)),
        updated_at=parse_time(pick(raw, F_MSG_UPDATED)),
        type=mtype,
    )


def parse_thread(raw: Any) -> Thread | None:
    """One thread, or None (with a WARN) if it lacks an id or any usable timestamp."""
    if not isinstance(raw, dict):
        log.warning("Politiloggen: thread is not an object, skipped")
        return None
    tid = _str(pick(raw, F_ID))
    if not tid:
        log.warning("Politiloggen: thread without id, skipped")
        return None

    raw_msgs = pick(raw, F_MESSAGES)
    if not isinstance(raw_msgs, list):
        raw_msgs = []
    by_seq: dict[int, Message] = {}
    unparsed = 0
    for rm in raw_msgs:
        msg = parse_message(rm, tid)
        if msg is None:
            if not _is_hidden(rm):
                unparsed += 1
        else:
            if msg.seq in by_seq:
                log.warning("Politiloggen thread %s: duplicate message seq %d, kept the first", tid, msg.seq)
                continue
            by_seq[msg.seq] = msg
    messages = tuple(sorted(by_seq.values(), key=lambda x: x.seq))

    # §8.3: first_message_at = earliest message time; the thread's created field only if
    # no message has a timestamp.
    msg_times = [m.created_at for m in messages if m.created_at]
    first = min(msg_times) if msg_times else parse_time(pick(raw, F_CREATED))
    last = parse_time(pick(raw, F_LAST_MESSAGE)) or (max(msg_times) if msg_times else None)
    if first is None and last is None:
        log.warning("Politiloggen thread %s: no usable timestamp, skipped", tid)
        return None
    first = first or last
    last = last or first
    assert first is not None and last is not None
    if last < first:
        last = first

    return Thread(
        id=tid,
        district=_str(pick(raw, F_DISTRICT)),
        municipality=_str(pick(raw, F_MUNICIPALITY)),
        area=_str(pick(raw, F_AREA)),
        category=_str(pick(raw, F_CATEGORY)) or UNKNOWN_CATEGORY,
        first_message_at=first,
        last_message_at=last,
        is_active=_bool(pick(raw, F_ACTIVE)),
        messages=messages,
        raw=raw,
        unparsed_messages=unparsed,
    )


def parse_page(payload: Any) -> Page:
    """A `/messagethreads` response. Never raises: a payload of the wrong shape gives an empty,
    `malformed` page with has_more=False, so the caller stops paging and can count it as a
    failed poll."""
    if not isinstance(payload, dict):
        log.warning("Politiloggen: response is %s, not an object", type(payload).__name__)
        return Page([], has_more=False, malformed=True)
    lower = {k.lower(): v for k, v in payload.items()}
    raw_threads = next((lower[n.lower()] for n in F_THREADS if n.lower() in lower), None)
    if raw_threads is None:
        raw_threads = []
    if not isinstance(raw_threads, list):
        log.warning("Politiloggen: messageThreads is %s, not a list", type(raw_threads).__name__)
        return Page([], has_more=False, malformed=True)
    has_more = next((lower[n.lower()] for n in F_HAS_MORE if n.lower() in lower), False)

    threads: list[Thread] = []
    seen: set[str] = set()
    skipped = 0
    for rt in raw_threads:
        t = parse_thread(rt)
        if t is None:
            skipped += 1
        elif t.id not in seen:  # dedupe within the page, as hent_trader does
            seen.add(t.id)
            threads.append(t)
    return Page(threads, has_more=_bool(has_more) is True, skipped=skipped, size=len(raw_threads))
