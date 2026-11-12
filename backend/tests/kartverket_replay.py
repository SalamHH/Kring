"""Recorded Kartverket responses and an offline replayer.

Each record holds one request and its response:
    {"url": ..., "params": {name: str}, "status": int, "body": <json or null>}
keyed by a hash of the url + sorted params, so the same request always maps to the same
record. Requests that have no recording fail the test (no network in tests).

Two stores, merged by load_all():
- tests/fixtures/kartverket/*.json: one file per request, for the Appendix C inputs.
- tests/fixtures/kartverket/threads.jsonl.gz: one gzipped line per request, for the
  recorded Oslo Politiloggen threads (too many requests for one file each).
"""

from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path
from typing import Any

import httpx

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "kartverket"
BUNDLE = FIXTURE_DIR / "threads.jsonl.gz"


def request_key(url: str, params: dict[str, Any]) -> str:
    canonical = json.dumps([url, sorted((k, str(v)) for k, v in params.items())], ensure_ascii=False)
    return hashlib.sha1(canonical.encode()).hexdigest()[:16]


def save(url: str, params: dict[str, Any], status: int, body: Any) -> Path:
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    path = FIXTURE_DIR / f"{request_key(url, params)}.json"
    path.write_text(
        json.dumps(record(url, params, status, body), ensure_ascii=False, indent=1, sort_keys=True) + "\n",
        "utf-8",
    )
    return path


def record(url: str, params: dict[str, Any], status: int, body: Any) -> dict[str, Any]:
    return {"url": url, "params": {k: str(v) for k, v in params.items()}, "status": status, "body": body}


def load_bundle() -> dict[str, dict[str, Any]]:
    if not BUNDLE.exists():
        return {}
    with gzip.open(BUNDLE, "rt", encoding="utf-8") as f:
        recs = [json.loads(line) for line in f if line.strip()]
    return {request_key(r["url"], r["params"]): r for r in recs}


def save_bundle(records: dict[str, dict[str, Any]]) -> None:
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    # mtime=0 keeps the file byte-identical when the content is unchanged
    with open(BUNDLE, "wb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as gz:
        for key in sorted(records):
            gz.write((json.dumps(records[key], ensure_ascii=False, sort_keys=True) + "\n").encode())


def load_files() -> dict[str, dict[str, Any]]:
    return {p.stem: json.loads(p.read_text("utf-8")) for p in sorted(FIXTURE_DIR.glob("*.json"))}


def load_all() -> dict[str, dict[str, Any]]:
    return {**load_bundle(), **load_files()}


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
