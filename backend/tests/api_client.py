"""An in-process API client whose requests run on a given test connection (inside its
transaction, with a savepoint per request), so a test can mix API calls and SQL."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from app.api.deps import get_session, session_scope
from app.api.main import create_app
from app.settings import Settings


@asynccontextmanager
async def api_client(
    conn: AsyncConnection, settings: Settings | None = None
) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(settings or Settings(rate_limit_per_minute=10_000, register_limit_per_hour=10_000))

    async def test_session() -> AsyncIterator[AsyncSession]:
        async with session_scope(AsyncSession(bind=conn, join_transaction_mode="create_savepoint")) as s:
            yield s

    app.dependency_overrides[get_session] = test_session
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def device(client: httpx.AsyncClient) -> dict[str, str]:
    r = await client.post("/v1/devices")
    assert r.status_code == 201, r.text
    return {"Authorization": f"Bearer {r.json()['secret']}"}
