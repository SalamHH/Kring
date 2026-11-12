"""Record live Politiloggen and kommuneinfo responses for offline tests (M0 step 6).

Writes to tests/fixtures/politiloggen/:
- kommuner.json      the kommuneinfo municipality list
- page_sample.json   one raw /messagethreads page (take=100, LastDay), all of Norway
- quarter.json       every LastQuarter thread whose municipality is in the allowed set
                     (Oslo + Akershus), raw, with the time of recording

Usage, from backend/:
    uv run python -m scripts.record_politiloggen

Hits the public APIs: a handful of requests, 1 s apart.
"""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from app.geocode.kartverket import USER_AGENT
from app.ingest.kommuner import KommuneRegister, in_scope
from app.ingest.politiloggen import parse_page
from app.settings import get_settings

OUT = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "politiloggen"
QUARTER_PAGE = 1000  # Swagger: Take ≤ 1000


def write(name: str, data: Any) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / name).write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", "utf-8")
    print(f"wrote {OUT / name}")


def main() -> None:
    s = get_settings()
    headers = {"Accept": "application/json", "User-Agent": USER_AGENT}
    with httpx.Client(headers=headers, timeout=60.0) as http:

        def get(url: str, params: dict[str, Any] | None = None) -> Any:
            resp = http.get(url, params=params)
            resp.raise_for_status()
            time.sleep(1.0)
            return resp.json()

        kommuner = get(s.kommuneinfo_url)
        write("kommuner.json", kommuner)
        register = KommuneRegister(kommuner)

        base = {"sortByEnum": "LastMessageOn"}
        write(
            "page_sample.json",
            get(s.politiloggen_url, {**base, "take": 100, "skip": 0, "timeSpanType": "LastDay"}),
        )

        recorded_at = datetime.now(UTC).isoformat()
        raw: dict[str, dict[str, Any]] = {}
        skip = 0
        while True:
            data = get(
                s.politiloggen_url,
                {**base, "take": QUARTER_PAGE, "skip": skip, "timeSpanType": "LastQuarter"},
            )
            page = parse_page(data)
            for st in in_scope(page.threads, register, s.allowed_fylker):
                raw.setdefault(st.thread.id, st.thread.raw)
            print(f"  skip={skip}: {page.size} threads, {len(raw)} in scope so far")
            if page.size == 0 or not page.has_more:
                break
            skip += page.size

        write(
            "quarter.json",
            {
                "recorded_at": recorded_at,
                "timeSpanType": "LastQuarter",
                "allowed_fylker": s.allowed_fylker,
                "threads": list(raw.values()),
            },
        )


if __name__ == "__main__":
    main()
