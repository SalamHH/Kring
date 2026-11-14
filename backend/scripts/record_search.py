"""Record the Kartverket responses the step 5 tests replay (tests/fixtures/kartverket/api/search.json).

Runs the API's own client methods (the same parameters the API sends) against the live
services and stores each request (path + query) with its status and body. Calls the public
Kartverket APIs; re-run to refresh:

    uv run python -m scripts.record_search
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import httpx

from app.api.main import api_kartverket
from app.settings import get_settings

OUT = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "kartverket" / "api" / "search.json"

QUERIES = ["Tøyen skole*", "Hølandsgata 1*", "Tøyen*"]
POINTS = {
    "Tøyen skole": (59.91483, 10.77318),
    "Hølandsgata 1A": (59.9089, 10.77923),
    "Trondheim torg": (63.43049, 10.39506),
    "Nordsjøen": (58.5, 3.0),
}


async def main() -> None:
    recorded: list[dict[str, Any]] = []

    async def hook(resp: httpx.Response) -> None:
        await resp.aread()
        body: Any
        try:
            body = resp.json()
        except ValueError:
            body = resp.text
        recorded.append(
            {
                "path": resp.request.url.path,
                "params": dict(sorted(resp.request.url.params.items())),
                "status": resp.status_code,
                "body": body,
            }
        )

    async with httpx.AsyncClient(event_hooks={"response": [hook]}) as http:
        client = api_kartverket(get_settings(), http)
        for q in QUERIES:
            await client.sok_adresser(q, 10)
            await client.sok_stedsnavn(q, 10)
        for lat, lon in POINTS.values():
            await client.kommune_for_punkt(lat, lon)
    OUT.write_text(json.dumps(recorded, ensure_ascii=False, indent=1) + "\n")
    print(f"{len(recorded)} responses -> {OUT}")


if __name__ == "__main__":
    asyncio.run(main())
