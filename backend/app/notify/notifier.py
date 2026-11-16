"""The notifier (spec §6.2, §8.7; D2, D6, D7): runs in the worker after each ingest commit.

1. **Plan**, in one transaction:
   - For each event the notifier hasn't handled (`events.notified_at IS NULL`), oldest first, find
     who gets a push, insert a `notifications` row per push (status `pending`) *before* sending,
     and mark the event handled.
   - The unique key (place, event, kind) means a (place, event) pair is never pushed twice, across
     cycles and restarts.
   - Normal events go to every matched place (§8.5) that passes the §6.2 push rules.
   - District-wide Savnet notices go to places in the district that follow Savnet, at most one per
     device, to the device's oldest qualifying place. The device row is locked while that is
     decided (D2). Other district notices are never pushed.
   - An event first seen more than `push_late_after_s` after it was stored (the worker died between
     ingest and notify) is marked handled without a push (decided 2026-11-14).
2. **Deliver**: send to Expo in batches of ≤ 100, and record each ticket on its row (`sent` with the
   ticket id, or `error:<code>`). In dry run, log instead (`dry_run`). A token Expo reports as
   DeviceNotRegistered is set to NULL.
3. **Receipts**: rows `sent` more than 15 minutes ago get their receipt (`ok` or `error:<code>`).
   A receipt still missing after a day is `receipt_missing`.

Events placed or improved later (a thread update, the step 1 command) are never pushed: they were
already handled when first stored. Updates never re-push.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Protocol

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.match.categories import app_category
from app.match.rules import places_for_event
from app.notify.copy import DISTRICT_BODY, district_title, push_body, push_title
from app.notify.expo import ExpoClient, ExpoFailed, error_code
from app.notify.rules import Facts, day_bounds, why_not
from app.settings import Settings

log = logging.getLogger("app.notify")

DEVICE_NOT_REGISTERED = "DeviceNotRegistered"


class Begins(Protocol):
    """An AsyncEngine, or anything with the same begin() (tests use savepoints)."""

    def begin(self) -> AbstractAsyncContextManager[AsyncConnection]: ...


@dataclass
class Outgoing:
    notification_id: int
    token: str
    title: str
    body: str
    event_id: str
    place_id: str

    def message(self) -> dict[str, Any]:
        return {
            "to": self.token,
            "title": self.title,
            "body": self.body,
            "data": {"event_id": self.event_id, "place_id": self.place_id},
            "sound": "default",
            "priority": "high",
        }


@dataclass
class NotifyResult:
    events: int = 0  # events handled this run
    late: int = 0  # handled without a push because the notifier saw them too late
    planned: int = 0  # notifications rows inserted
    sent: int = 0  # accepted by Expo (or logged, in dry run)
    failed: int = 0
    receipts_ok: int = 0
    receipts_error: int = 0
    skipped: dict[str, int] = field(default_factory=dict)  # why matched places got no push

    def skip(self, reason: str) -> None:
        self.skipped[reason] = self.skipped.get(reason, 0) + 1


def _window(v: Any) -> dict[str, Any]:
    return v if isinstance(v, dict) else json.loads(v)


class Notifier:
    def __init__(
        self, settings: Settings, expo: ExpoClient | None, clock: Callable[[], datetime] | None = None
    ) -> None:
        self.settings = settings
        self.expo = expo
        self.dry_run = settings.push_dry_run or expo is None
        self._clock = clock  # tests set it; otherwise the database's clock_timestamp()

    async def _now(self, conn: AsyncConnection) -> datetime:
        if self._clock is not None:
            return self._clock()
        return (await conn.execute(text("SELECT clock_timestamp()"))).scalar_one()

    async def run(self, engine: Begins) -> NotifyResult:
        res = NotifyResult()
        async with engine.begin() as conn:
            outgoing = await self.plan(conn, res)
        if outgoing:
            async with engine.begin() as conn:
                await self.deliver(conn, outgoing, res)
        if not self.dry_run:
            async with engine.begin() as conn:
                await self.poll_receipts(conn, res)
        if res.events or res.planned or res.receipts_ok or res.receipts_error:
            log.info(
                "notify: %d events, %d late, %d pushes planned, %d sent%s, %d failed, "
                "receipts %d ok / %d error; no push: %s",
                res.events, res.late, res.planned, res.sent, " (dry run)" if self.dry_run else "", res.failed,
                res.receipts_ok, res.receipts_error,
                ", ".join(f"{k} {v}" for k, v in sorted(res.skipped.items())) or "-",
            )  # fmt: skip
        return res

    # --- 1. plan ------------------------------------------------------------------------------

    async def plan(self, conn: AsyncConnection, res: NotifyResult) -> list[Outgoing]:
        now = await self._now(conn)
        pending = (
            await conn.execute(
                text("""
                    SELECT id, scope, category, severity, first_message_at, ingested_at, is_active,
                           precision_tier, geocode_method, geocode_match, area, municipality, district
                    FROM events WHERE notified_at IS NULL
                    ORDER BY ingested_at NULLS FIRST, id
                    FOR UPDATE SKIP LOCKED
                """)
            )
        ).all()
        outgoing: list[Outgoing] = []
        late = timedelta(seconds=self.settings.push_late_after_s)
        for e in pending:
            res.events += 1
            if e.ingested_at is None or now - e.ingested_at > late:
                res.late += 1
            elif e.scope == "distrikt":
                outgoing += await self._plan_district(conn, e, now, res)
            else:
                outgoing += await self._plan_event(conn, e, now, res)
        if pending:
            await conn.execute(
                text("UPDATE events SET notified_at = :now WHERE id = ANY(:ids)"),
                {"ids": [e.id for e in pending], "now": now},
            )
        return outgoing

    async def _pushes_today(self, conn: AsyncConnection, place_id: Any, now: datetime, tz: str) -> int:
        start, end = day_bounds(now, tz)
        return int(
            (
                await conn.execute(
                    text("""
                        SELECT count(*) FROM notifications
                        WHERE place_id = :p AND kind = 'push' AND sent_at >= :s AND sent_at < :e
                    """),
                    {"p": place_id, "s": start, "e": end},
                )
            ).scalar_one()
        )

    def _facts(self, e: Any, place: Any, tz: str, token: str | None, pushes_today: int) -> Facts:
        return Facts(
            severe=e.severity == "severe",
            first_message_at=e.first_message_at,
            ingested_at=e.ingested_at,
            window=_window(place.time_window),
            tz=tz,
            pushes_today=pushes_today,
            push_on=place.push,
            has_token=bool(token),
        )

    def _why_not(self, f: Facts) -> str | None:
        return why_not(
            f, max_age_min=self.settings.push_max_age_min, daily_limit=self.settings.push_daily_limit
        )

    async def _insert(self, conn: AsyncConnection, place_id: Any, event_id: str, now: datetime) -> int | None:
        row = (
            await conn.execute(
                text("""
                    INSERT INTO notifications (place_id, event_id, kind, status, sent_at)
                    VALUES (:p, :e, 'push', 'pending', :now)
                    ON CONFLICT (place_id, event_id, kind) DO NOTHING
                    RETURNING id
                """),
                {"p": place_id, "e": event_id, "now": now},
            )
        ).first()
        return row[0] if row else None

    async def _devices(self, conn: AsyncConnection, ids: list[Any]) -> dict[Any, Any]:
        rows = await conn.execute(
            text("SELECT id, tz, push_token FROM devices WHERE id = ANY(:ids)"), {"ids": ids}
        )
        return {r.id: r for r in rows}

    async def _plan_event(
        self, conn: AsyncConnection, e: Any, now: datetime, res: NotifyResult
    ) -> list[Outgoing]:
        if e.severity != "severe":
            return []  # nothing to push; skip the place lookup
        places = await places_for_event(conn, e.id)
        if not places:
            return []
        devices = await self._devices(conn, list({p.device_id for p in places}))
        out: list[Outgoing] = []
        for p in places:
            d = devices[p.device_id]
            facts = self._facts(e, p, d.tz, d.push_token, await self._pushes_today(conn, p.id, now, d.tz))
            reason = self._why_not(facts)
            if reason:
                res.skip(reason)
                continue
            nid = await self._insert(conn, p.id, e.id, now)
            if nid is None:
                res.skip("already pushed")
                continue
            res.planned += 1
            title = push_title(category=e.category, distance_m=p.distance_m, place_label_text=p.label)
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
            out.append(Outgoing(nid, d.push_token, title, body, e.id, str(p.id)))
        return out

    async def _plan_district(
        self, conn: AsyncConnection, e: Any, now: datetime, res: NotifyResult
    ) -> list[Outgoing]:
        if app_category(e.category) != "Savnet":
            return []  # D2: other district notices are never pushed
        rows = (
            await conn.execute(
                text("""
                    SELECT p.id, p.device_id, p.label, p.time_window, p.push, p.created_at
                    FROM places p
                    WHERE 'Savnet' = ANY (p.categories)
                      AND p.kommunenummer IN (
                        SELECT DISTINCT kommunenummer FROM events
                        WHERE scope = 'kommune' AND kommunenummer IS NOT NULL
                          AND lower(district) = lower(:district)
                      )
                    ORDER BY p.device_id, p.created_at, p.id
                """),
                {"district": e.district or e.municipality},
            )
        ).all()
        by_device: dict[Any, list[Any]] = {}
        for r in rows:
            by_device.setdefault(r.device_id, []).append(r)
        out: list[Outgoing] = []
        for device_id, places in by_device.items():
            # Lock the device: the notifications key is per place, so «once per device» is
            # checked here (D2).
            d = (
                await conn.execute(
                    text("SELECT id, tz, push_token FROM devices WHERE id = :d FOR UPDATE"), {"d": device_id}
                )
            ).one()
            already = (
                await conn.execute(
                    text("""
                        SELECT 1 FROM notifications n JOIN places p ON p.id = n.place_id
                        WHERE n.event_id = :e AND n.kind = 'push' AND p.device_id = :d
                    """),
                    {"e": e.id, "d": device_id},
                )
            ).first()
            if already:
                res.skip("already pushed")
                continue
            for p in places:  # oldest first
                facts = self._facts(e, p, d.tz, d.push_token, await self._pushes_today(conn, p.id, now, d.tz))
                reason = self._why_not(facts)
                if reason:
                    res.skip(reason)
                    continue
                nid = await self._insert(conn, p.id, e.id, now)
                if nid is None:
                    continue
                res.planned += 1
                title = district_title(category=e.category, district=e.district or e.municipality)
                out.append(Outgoing(nid, d.push_token, title, DISTRICT_BODY, e.id, str(p.id)))
                break
        return out

    # --- 2. deliver ---------------------------------------------------------------------------

    async def _set(self, conn: AsyncConnection, nid: int, status: str, ticket_id: str | None = None) -> None:
        # sent_at becomes the time Expo accepted it (step 13 measures latency to it).
        await conn.execute(
            text("""
                UPDATE notifications SET status = :s, ticket_id = COALESCE(:t, ticket_id), sent_at = :now
                WHERE id = :id
            """),
            {"s": status, "t": ticket_id, "id": nid, "now": await self._now(conn)},
        )

    async def _forget_token(self, conn: AsyncConnection, token: str) -> None:
        await conn.execute(text("UPDATE devices SET push_token = NULL WHERE push_token = :t"), {"t": token})

    async def deliver(self, conn: AsyncConnection, outgoing: list[Outgoing], res: NotifyResult) -> None:
        if self.dry_run:
            for o in outgoing:
                log.info(
                    "push (dry run): event %s → place %s: %s | %s", o.event_id, o.place_id, o.title, o.body
                )
                await self._set(conn, o.notification_id, "dry_run")
                res.sent += 1
            return
        assert self.expo is not None
        try:
            tickets = await self.expo.send([o.message() for o in outgoing])
        except ExpoFailed as e:
            log.error("notify: Expo send failed for %d pushes: %s", len(outgoing), e)
            for o in outgoing:
                await self._set(conn, o.notification_id, "error:send_failed")
            res.failed += len(outgoing)
            return
        for o, t in zip(outgoing, tickets, strict=True):
            if t.get("status") == "ok" and t.get("id"):
                await self._set(conn, o.notification_id, "sent", str(t["id"]))
                res.sent += 1
                log.info("push: event %s → place %s: %s", o.event_id, o.place_id, o.title)
                continue
            code = error_code(t)
            await self._set(conn, o.notification_id, f"error:{code}")
            res.failed += 1
            log.warning("notify: push for event %s → place %s rejected: %s", o.event_id, o.place_id, code)
            if code == DEVICE_NOT_REGISTERED:
                await self._forget_token(conn, o.token)

    # --- 3. receipts --------------------------------------------------------------------------

    async def poll_receipts(self, conn: AsyncConnection, res: NotifyResult) -> None:
        assert self.expo is not None
        rows = (
            await conn.execute(
                text("""
                    SELECT n.id, n.ticket_id, p.device_id,
                           n.sent_at < CAST(:now AS timestamptz) - make_interval(secs => :give_up) AS expired
                    FROM notifications n JOIN places p ON p.id = n.place_id
                    WHERE n.status = 'sent'
                      AND n.sent_at < CAST(:now AS timestamptz) - make_interval(secs => :delay)
                    ORDER BY n.sent_at
                    LIMIT 1000
                """),
                {
                    "delay": self.settings.receipt_delay_s,
                    "give_up": self.settings.receipt_give_up_s,
                    "now": await self._now(conn),
                },
            )
        ).all()
        if not rows:
            return
        try:
            receipts = await self.expo.receipts([r.ticket_id for r in rows])
        except ExpoFailed as e:
            log.warning("notify: Expo receipts failed, retried next cycle: %s", e)
            return
        for r in rows:
            rec = receipts.get(r.ticket_id)
            if rec is None:
                if r.expired:
                    await conn.execute(
                        text("UPDATE notifications SET status = 'receipt_missing' WHERE id = :id"),
                        {"id": r.id},
                    )
                continue
            if rec.get("status") == "ok":
                status = "ok"
                res.receipts_ok += 1
            else:
                code = error_code(rec)
                status = f"error:{code}"
                res.receipts_error += 1
                log.warning("notify: receipt for notification %d: %s", r.id, code)
                if code == DEVICE_NOT_REGISTERED:
                    await conn.execute(
                        text("UPDATE devices SET push_token = NULL WHERE id = :d"), {"d": r.device_id}
                    )
            await conn.execute(
                text("UPDATE notifications SET status = :s WHERE id = :id"), {"s": status, "id": r.id}
            )
