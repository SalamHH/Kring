"""M1 step 3: the API skeleton, devices and health (spec §8.6, §8.8).

Runs the app in-process (httpx ASGITransport) against the test database. Each request gets a
session on the test connection with a savepoint, so the whole test still rolls back.
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import AsyncIterator

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from app.api.deps import get_session, session_scope
from app.api.main import create_app
from app.api.ratelimit import RateLimiter
from app.settings import Settings


class FakeClock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
async def client(db: AsyncConnection, clock: FakeClock) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(Settings(rate_limit_per_minute=5, register_limit_per_hour=50))
    app.state.device_limiter = RateLimiter(5, 60, clock=clock)

    async def test_session() -> AsyncIterator[AsyncSession]:
        async with session_scope(AsyncSession(bind=db, join_transaction_mode="create_savepoint")) as s:
            yield s

    app.dependency_overrides[get_session] = test_session
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def auth(secret: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {secret}"}


async def register(client: httpx.AsyncClient, **body: str) -> tuple[str, str]:
    r = await client.post("/v1/devices", json=body or None)
    assert r.status_code == 201, r.text
    return r.json()["device_id"], r.json()["secret"]


async def count(db: AsyncConnection, sql: str, **params: object) -> int:
    return (await db.execute(text(sql), params)).scalar_one()


# --- devices -------------------------------------------------------------------------------


async def test_register_then_update_token(client: httpx.AsyncClient, db: AsyncConnection) -> None:
    device_id, secret = await register(client, platform="ios")
    row = (await db.execute(text("SELECT * FROM devices WHERE id = :id"), {"id": device_id})).one()
    assert row.platform == "ios" and row.tz == "Europe/Oslo" and row.push_token is None
    assert row.last_seen_at is not None

    r = await client.put(
        "/v1/devices/me",
        headers=auth(secret),
        json={"push_token": "ExponentPushToken[abc]", "tz": "Europe/London"},
    )
    assert r.status_code == 200, r.text
    assert r.json() == {
        "device_id": device_id,
        "platform": "ios",
        "tz": "Europe/London",
        "has_push_token": True,
    }
    row = (await db.execute(text("SELECT * FROM devices WHERE id = :id"), {"id": device_id})).one()
    assert row.push_token == "ExponentPushToken[abc]" and row.tz == "Europe/London"
    assert row.platform == "ios"  # not sent, not changed

    r = await client.put("/v1/devices/me", headers=auth(secret), json={"push_token": None})
    assert r.status_code == 200 and r.json()["has_push_token"] is False


async def test_register_without_body(client: httpx.AsyncClient) -> None:
    r = await client.post("/v1/devices")
    assert r.status_code == 201
    assert uuid.UUID(r.json()["device_id"])
    assert len(r.json()["secret"]) >= 43  # 32 bytes, base64url


@pytest.mark.parametrize(
    "headers",
    [{}, {"Authorization": "Bearer nope"}, {"Authorization": "Basic x"}, {"Authorization": "Bearer "}],
)
async def test_wrong_or_missing_secret_is_401(client: httpx.AsyncClient, headers: dict[str, str]) -> None:
    await register(client)
    for method in ("PUT", "DELETE"):
        r = await client.request(method, "/v1/devices/me", headers=headers, json={"tz": "Europe/Oslo"})
        assert r.status_code == 401, (method, r.text)
        assert r.headers["WWW-Authenticate"] == "Bearer"
        assert r.json()["error"] == "unauthorized"


async def test_another_devices_secret_does_not_work_after_delete(client: httpx.AsyncClient) -> None:
    _, secret = await register(client)
    assert (await client.delete("/v1/devices/me", headers=auth(secret))).status_code == 204
    r = await client.put("/v1/devices/me", headers=auth(secret), json={"tz": "Europe/Oslo"})
    assert r.status_code == 401


@pytest.mark.parametrize(
    "body",
    [
        {"platform": "windows"},
        {"tz": "Mars/Base"},
        {"tz": None},
        {"push_token": ""},
        {"push_token": "x" * 256},
        {"colour": "red"},
    ],
)
async def test_invalid_update_is_422_json(client: httpx.AsyncClient, body: dict[str, object]) -> None:
    _, secret = await register(client)
    r = await client.put("/v1/devices/me", headers=auth(secret), json=body)
    assert r.status_code == 422, r.text
    assert r.json()["error"] == "invalid_request" and r.json()["details"]


async def test_secret_is_stored_as_sha256(client: httpx.AsyncClient, db: AsyncConnection) -> None:
    device_id, secret = await register(client)
    stored = (
        await db.execute(text("SELECT secret_hash FROM devices WHERE id = :id"), {"id": device_id})
    ).scalar()
    assert stored == hashlib.sha256(secret.encode()).hexdigest()
    dump = await db.execute(text("SELECT row_to_json(d)::text FROM devices d"))
    assert all(secret not in r[0] for r in dump)


async def test_last_seen_updated_at_most_hourly(client: httpx.AsyncClient, db: AsyncConnection) -> None:
    device_id, secret = await register(client)
    seen = "SELECT last_seen_at FROM devices WHERE id = :id"
    await db.execute(
        text("UPDATE devices SET last_seen_at = now() - interval '59 minutes' WHERE id = :id"),
        {"id": device_id},
    )
    before = (await db.execute(text(seen), {"id": device_id})).scalar()
    await client.put("/v1/devices/me", headers=auth(secret), json={})
    assert (await db.execute(text(seen), {"id": device_id})).scalar() == before  # under an hour: untouched

    await db.execute(
        text("UPDATE devices SET last_seen_at = now() - interval '61 minutes' WHERE id = :id"),
        {"id": device_id},
    )
    await client.put("/v1/devices/me", headers=auth(secret), json={})
    now = (await db.execute(text("SELECT now()"))).scalar()
    assert (await db.execute(text(seen), {"id": device_id})).scalar() == now


async def test_delete_removes_device_places_and_notifications(
    client: httpx.AsyncClient, db: AsyncConnection
) -> None:
    keep_id, _ = await register(client)
    gone_id, secret = await register(client)
    await db.execute(
        text("""
        INSERT INTO events (id, category, severity, first_message_at, last_message_at, raw)
        VALUES ('ev-1', 'Brann', 'severe', now(), now(), '{}')
    """)
    )
    for device_id in (keep_id, gone_id):
        for _ in range(2):
            place_id = uuid.uuid4()
            await db.execute(
                text("""
                INSERT INTO places (id, device_id, label, template, center, radius_m, categories, time_window)
                VALUES (:p, :d, 'Hjemme', 'hjem', 'POINT(10.77 59.91)', 1000, '{Brann}', '{"all": true}')
            """),
                {"p": place_id, "d": device_id},
            )
            await db.execute(
                text("INSERT INTO notifications (place_id, event_id, kind) VALUES (:p, 'ev-1', 'push')"),
                {"p": place_id},
            )
            await db.execute(
                text("INSERT INTO placement_feedback (event_id, place_id) VALUES ('ev-1', :p)"),
                {"p": place_id},
            )

    async def counts(device_id: str) -> tuple[int, int, int, int]:
        p = {"d": device_id}
        places = "SELECT id FROM places WHERE device_id = :d"
        return (
            await count(db, "SELECT count(*) FROM devices WHERE id = :d", **p),
            await count(db, "SELECT count(*) FROM places WHERE device_id = :d", **p),
            await count(db, f"SELECT count(*) FROM notifications WHERE place_id IN ({places})", **p),
            await count(db, f"SELECT count(*) FROM placement_feedback WHERE place_id IN ({places})", **p),
        )

    assert await counts(gone_id) == (1, 2, 2, 2)
    assert await count(db, "SELECT count(*) FROM notifications") == 4
    assert await count(db, "SELECT count(*) FROM placement_feedback") == 4

    r = await client.delete("/v1/devices/me", headers=auth(secret))
    assert r.status_code == 204 and r.content == b""

    assert await counts(gone_id) == (0, 0, 0, 0)
    assert await counts(keep_id) == (1, 2, 2, 2)  # the other device is untouched
    assert await count(db, "SELECT count(*) FROM notifications") == 2
    assert await count(db, "SELECT count(*) FROM placement_feedback") == 2
    assert await count(db, "SELECT count(*) FROM events") == 1  # events are public data, kept


# --- rate limit ----------------------------------------------------------------------------


async def test_rate_limit_is_429_with_retry_after(client: httpx.AsyncClient, clock: FakeClock) -> None:
    _, secret = await register(client)
    _, other = await register(client)
    for _ in range(5):
        assert (await client.put("/v1/devices/me", headers=auth(secret), json={})).status_code == 200
    r = await client.put("/v1/devices/me", headers=auth(secret), json={})
    assert r.status_code == 429
    assert r.json()["error"] == "rate_limited"
    assert r.headers["Retry-After"] == "12"  # 5 a minute: one token every 12 s
    # Per device: another device is not limited.
    assert (await client.put("/v1/devices/me", headers=auth(other), json={})).status_code == 200
    clock.t += 12
    assert (await client.put("/v1/devices/me", headers=auth(secret), json={})).status_code == 200
    assert (await client.put("/v1/devices/me", headers=auth(secret), json={})).status_code == 429


async def test_registration_is_rate_limited_per_client(client: httpx.AsyncClient) -> None:
    for _ in range(50):
        assert (await client.post("/v1/devices")).status_code == 201
    r = await client.post("/v1/devices")
    assert r.status_code == 429 and int(r.headers["Retry-After"]) > 0


def test_rate_limiter_refills_and_prunes() -> None:
    clock = FakeClock()
    rl = RateLimiter(2, 10, clock=clock, max_keys=2)
    assert rl.hit("a") is None and rl.hit("a") is None
    assert rl.hit("a") == pytest.approx(5.0)
    clock.t += 2.5
    assert rl.hit("a") == pytest.approx(2.5)  # half a token back, not enough
    rl.hit("b")
    clock.t += 10
    rl.hit("c")  # both a and b are full again, so they are dropped to make room
    assert set(rl._buckets) == {"c"}


# --- health --------------------------------------------------------------------------------


async def set_last_success(db: AsyncConnection, ago: str | None) -> None:
    await db.execute(text("DELETE FROM ingest_state"))
    if ago is not None:
        await db.execute(
            text(f"INSERT INTO ingest_state (id, last_success_at) VALUES (true, now() - interval '{ago}')")
        )


async def test_health_ok(client: httpx.AsyncClient, db: AsyncConnection) -> None:
    await set_last_success(db, "90 seconds")
    r = await client.get("/v1/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok" and r.json()["age_s"] == 90 and r.json()["last_success_at"]


@pytest.mark.parametrize("ago", ["601 seconds", "3 hours", None])
async def test_health_503_when_stale(client: httpx.AsyncClient, db: AsyncConnection, ago: str | None) -> None:
    await set_last_success(db, ago)
    r = await client.get("/v1/health")
    assert r.status_code == 503
    assert r.json()["status"] == "stale"


async def test_health_needs_no_secret_and_unknown_paths_are_json(client: httpx.AsyncClient) -> None:
    r = await client.get("/v1/nope")
    assert r.status_code == 404 and r.json()["error"] == "not_found"


async def test_commit_failure_is_not_reported_as_success(db: AsyncConnection) -> None:
    """The transaction commits before the response: a failing commit is a 500, not a 201."""
    app = create_app(Settings())

    class FailingCommit(AsyncSession):
        async def commit(self) -> None:
            raise RuntimeError("commit failed")

    async def failing_session() -> AsyncIterator[AsyncSession]:
        async with session_scope(FailingCommit(bind=db, join_transaction_mode="create_savepoint")) as s:
            yield s

    app.dependency_overrides[get_session] = failing_session
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post("/v1/devices")
    assert r.status_code == 500
    assert r.json()["error"] == "internal_error"
    assert await count(db, "SELECT count(*) FROM devices") == 0
