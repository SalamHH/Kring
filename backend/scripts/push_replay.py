"""Replay stored events through the matcher and push rules for sample places, and report pushes
per place per week (spec §13 target: 0.5-2). M1 step 7. Read-only.

Assumes every event was detected in time (first message ≤ 30 min old when stored), since stored
events from before step 7 have no detection time. So this is an upper bound for real use.

    uv run python -m scripts.push_replay
"""

from __future__ import annotations

import asyncio
from collections import Counter
from datetime import timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.api.places import TEMPLATES
from app.match.rules import MATCH, Circle, events_near
from app.notify.rules import in_window, local
from app.settings import get_settings

# (label, template, lat, lon, radius)
PLACES = [
    ("Skole · Tøyen skole", "skole", 59.91483, 10.77318, 1000),
    ("Hjem · Grünerløkka", "hjem", 59.92254, 10.75925, 1000),
    ("Jobb · Oslo S", "jobb", 59.91087, 10.75286, 1000),
    ("Hjem · Sandvika (Bærum)", "hjem", 59.88925, 10.52476, 1000),
    ("Skole · Lillestrøm, 500 m", "skole", 59.95581, 11.04974, 500),
]
TZ = "Europe/Oslo"
DAILY_LIMIT = 3


async def main() -> None:
    engine = create_async_engine(get_settings().database_url)
    async with engine.connect() as conn:
        first, last = (
            await conn.execute(text("SELECT min(first_message_at), max(first_message_at) FROM events"))
        ).one()
        weeks = (last - first) / timedelta(weeks=1)
        print(f"Events from {first:%Y-%m-%d} to {last:%Y-%m-%d}: {weeks:.1f} weeks\n")
        print("| Place | Matched | Severe | Pushes | Per week |")
        print("|---|---:|---:|---:|---:|")
        for label, template, lat, lon, radius in PLACES:
            cats, window = TEMPLATES[template]
            rows = await events_near(conn, Circle(lat, lon, radius), cats, first)
            matched = [r for r in rows if r.relation == MATCH]
            severe = [r for r in matched if r.severity == "severe"]
            per_day: Counter[str] = Counter()
            pushes = 0
            for r in sorted(severe, key=lambda r: r.first_message_at):
                if not in_window(window, r.first_message_at, TZ):
                    continue
                day = local(r.first_message_at, TZ).date().isoformat()
                if per_day[day] >= DAILY_LIMIT:
                    continue
                per_day[day] += 1
                pushes += 1
            print(f"| {label} | {len(matched)} | {len(severe)} | {pushes} | {pushes / weeks:.2f} |")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
