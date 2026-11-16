"""Send one test push to a place's device, as the notifier would, to check the phone end to end
(M1 step 12): Expo → APNs → the phone, and tapping it opens Hendelse for that incident.

Run in the worker shell on Render (docs/deploy.md), or locally:

    uv run --no-sync python -m scripts.test_push            # shows what it would send
    uv run --no-sync python -m scripts.test_push --send     # sends it, then reads the receipt

- The place is the newest one whose device has a push token, or `--place-id`.
- The incident is the newest that matches the place in the last 90 days; failing that, the newest
  incident within 2 km in any category, so there is always something to open.
- The title starts with «Test:». The data is `{event_id, place_id}`, as in §8.7.
- It writes nothing: no `notifications` row, so the real notifier and the step 13 statistics are
  unaffected. The push token is never printed.
"""

from __future__ import annotations

import argparse
import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from app.match.categories import APP_CATEGORIES
from app.match.rules import Circle, events_near
from app.notify.copy import push_body, push_title
from app.notify.expo import ExpoClient, error_code
from app.settings import get_settings

MATCH_DAYS = 90
FALLBACK_RADIUS_M = 2000
RECEIPT_WAIT_S = 15


async def find_place(conn: AsyncConnection, place_id: uuid.UUID | None) -> Any:
    rows = await conn.execute(
        text("""
            SELECT p.id, p.label, p.radius_m, p.categories, p.created_at,
                   ST_Y(p.center::geometry) AS lat, ST_X(p.center::geometry) AS lon,
                   d.push_token, d.platform
            FROM places p JOIN devices d ON d.id = p.device_id
            WHERE d.push_token IS NOT NULL AND (CAST(:id AS uuid) IS NULL OR p.id = :id)
            ORDER BY p.created_at DESC
            LIMIT 1
        """),
        {"id": place_id},
    )
    return rows.one_or_none()


async def find_event(conn: AsyncConnection, place: Any) -> tuple[Any, str] | None:
    since = datetime.now(UTC) - timedelta(days=MATCH_DAYS)
    circle = Circle(place.lat, place.lon, place.radius_m)
    for r in await events_near(conn, circle, list(place.categories), since):
        if r.relation == "match":
            return r, "matches the place"
    wide = Circle(place.lat, place.lon, FALLBACK_RADIUS_M)
    near = await events_near(conn, wide, list(APP_CATEGORIES), since)
    if near:
        return near[0], f"no match; nearest incident within {FALLBACK_RADIUS_M} m instead"
    return None


async def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--place-id", type=uuid.UUID, help="the place (default: the newest with a token)")
    ap.add_argument("--send", action="store_true", help="send it (default: only show it)")
    args = ap.parse_args()

    settings = get_settings()
    engine = create_async_engine(settings.database_url)
    try:
        async with engine.connect() as conn:
            place = await find_place(conn, args.place_id)
            if place is None:
                raise SystemExit("No place whose device has a push token. Allow notifications first.")
            found = await find_event(conn, place)
            if found is None:
                raise SystemExit(f"No incident within {FALLBACK_RADIUS_M} m in {MATCH_DAYS} days.")
            e, why = found
    finally:
        await engine.dispose()

    title = "Test: " + push_title(category=e.category, distance_m=e.distance_m, place_label_text=place.label)
    body = push_body(
        category=e.category,
        is_active=e.is_active,
        precision_tier=e.precision_tier,
        geocode_method=e.geocode_method,
        geocode_match=e.geocode_match,
        area=e.area,
        municipality=e.municipality,
        district=e.district,
    )
    print(f"place:  «{place.label}» {place.id} ({place.platform}, made {place.created_at:%Y-%m-%d %H:%M})")
    first = f"{e.first_message_at:%Y-%m-%d %H:%M}"
    print(f"event:  {e.id} ({why}, {round(e.distance_m)} m, first message {first})")
    print(f"title:  {title}")
    print(f"body:   {body}")
    print(f"data:   {{'event_id': '{e.id}', 'place_id': '{place.id}'}}")
    if not args.send:
        print("Not sent. Add --send to send it.")
        return

    message = {
        "to": place.push_token,
        "title": title,
        "body": body,
        "data": {"event_id": e.id, "place_id": str(place.id)},
        "sound": "default",
        "priority": "high",
    }
    async with httpx.AsyncClient() as http:
        s = settings
        expo = ExpoClient(http, s.expo_push_url, s.expo_receipts_url, s.expo_access_token)
        [ticket] = await expo.send([message])
        if ticket.get("status") != "ok":
            raise SystemExit(f"Expo refused it: {error_code(ticket)}")
        print(f"sent:   ticket {ticket['id']}; reading the receipt in {RECEIPT_WAIT_S} s …")
        await asyncio.sleep(RECEIPT_WAIT_S)
        receipt = (await expo.receipts([ticket["id"]])).get(ticket["id"])
        if receipt is None:
            print("receipt: not ready yet (Expo can take a few minutes); the push may still arrive.")
        elif receipt.get("status") == "ok":
            print("receipt: ok — Apple accepted it.")
        else:
            print(f"receipt: error {error_code(receipt)}")


if __name__ == "__main__":
    asyncio.run(main())
