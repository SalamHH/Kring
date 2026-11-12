"""Recorded Kartverket responses (tests/fixtures/kartverket/*.json) and an offline replayer.

Each file holds one request and its response:
    {"url": ..., "params": {name: str}, "status": int, "body": <json or null>}
The file name is a hash of the url + sorted params, so the same request always maps to
the same file. Requests that have no recording fail the test (no network in tests).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import httpx

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "kartverket"


def request_key(url: str, params: dict[str, Any]) -> str:
    canonical = json.dumps([url, sorted((k, str(v)) for k, v in params.items())], ensure_ascii=False)
    return hashlib.sha1(canonical.encode()).hexdigest()[:16]


def save(url: str, params: dict[str, Any], status: int, body: Any) -> Path:
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    path = FIXTURE_DIR / f"{request_key(url, params)}.json"
    record = {"url": url, "params": {k: str(v) for k, v in params.items()}, "status": status, "body": body}
    path.write_text(json.dumps(record, ensure_ascii=False, indent=1, sort_keys=True) + "\n", "utf-8")
    return path


def load_all() -> dict[str, dict[str, Any]]:
    return {p.stem: json.loads(p.read_text("utf-8")) for p in sorted(FIXTURE_DIR.glob("*.json"))}


class UnrecordedRequest(AssertionError):
    pass


def replay_handler(records: dict[str, dict[str, Any]] | None = None):
    """A respx side_effect that answers from the recordings."""
    records = load_all() if records is None else records

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url.copy_with(query=None))
        params = dict(request.url.params.multi_items())
        rec = records.get(request_key(url, params))
        if rec is None:
            raise UnrecordedRequest(f"no recording for {url} {params}")
        if rec["body"] is None:
            return httpx.Response(rec["status"])
        return httpx.Response(rec["status"], json=rec["body"])

    return handler
