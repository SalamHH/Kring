"""Print event counts and the poll status, to compare two databases (e.g. production with
local, M1 step 4). Uses KRING_DATABASE_URL like everything else:

    uv run python -m scripts.db_counts
"""

from __future__ import annotations

import asyncio

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.settings import get_settings

QUERIES = {
    "events by scope": "SELECT scope, count(*) FROM events GROUP BY 1 ORDER BY 1",
    "events by fylke": "SELECT left(kommunenummer, 2), count(*) FROM events GROUP BY 1 ORDER BY 1",
    "events by tier": "SELECT precision_tier, count(*) FROM events GROUP BY 1 ORDER BY 1",
    "events last 24 h": "SELECT 'first message in the last 24 h', count(*) FROM events "
    "WHERE first_message_at > now() - interval '24 hours'",
    "first and last message": "SELECT min(first_message_at)::text, max(last_message_at)::text FROM events",
    "devices and places": "SELECT (SELECT count(*) FROM devices), (SELECT count(*) FROM places)",
    "notifications by status": "SELECT status, count(*) FROM notifications GROUP BY 1 ORDER BY 1",
    "ingest_state": "SELECT last_success_at::text, last_error_at::text, last_error FROM ingest_state",
}


async def main() -> None:
    engine = create_async_engine(get_settings().database_url)
    try:
        async with engine.connect() as conn:
            for title, sql in QUERIES.items():
                print(f"{title}:")
                for row in await conn.execute(text(sql)):
                    print("  " + " | ".join("—" if v is None else str(v) for v in row))
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
