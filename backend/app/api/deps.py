"""Request dependencies: a database session per request, and the calling device (§8.6, §8.8)."""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import ApiError
from app.api.ratelimit import retry_after_header


@asynccontextmanager
async def session_scope(session: AsyncSession) -> AsyncIterator[AsyncSession]:
    """One transaction per request: committed if the handler returns, rolled back if it raises."""
    try:
        yield session
        await session.commit()
    except BaseException:
        await session.rollback()
        raise
    finally:
        await session.close()


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    async with session_scope(request.app.state.sessionmaker()) as s:
        yield s


# scope="function": commit before the response is sent, so a client never sees a 2xx for a write
# that then fails to commit (FastAPI's default exits yield dependencies after the response).
Session = Annotated[AsyncSession, Depends(get_session, scope="function")]


def hash_secret(secret: str) -> str:
    """SHA-256, hex. The secret is 32 random bytes, so a fast hash is enough (no brute force)."""
    return hashlib.sha256(secret.encode()).hexdigest()


@dataclass(frozen=True)
class Device:
    id: uuid.UUID


_bearer = HTTPBearer(auto_error=False)


def unauthorized() -> ApiError:
    return ApiError(
        401, "unauthorized", "Missing or invalid device secret", headers={"WWW-Authenticate": "Bearer"}
    )


async def current_device(
    request: Request,
    session: Session,
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> Device:
    if creds is None or not creds.credentials:
        raise unauthorized()
    row = (
        await session.execute(
            text("""
                SELECT id, last_seen_at IS NULL OR last_seen_at < now() - interval '1 hour' AS stale
                FROM devices WHERE secret_hash = :h
            """),
            {"h": hash_secret(creds.credentials)},
        )
    ).one_or_none()
    if row is None:
        raise unauthorized()
    wait = request.app.state.device_limiter.hit(str(row.id))
    if wait is not None:
        raise ApiError(
            429, "rate_limited", "Too many requests", headers={"Retry-After": retry_after_header(wait)}
        )
    # last_seen_at drives the 12-month inactive-device deletion (§8.8); hourly is precise enough
    # and keeps most requests read-only.
    if row.stale:
        await session.execute(text("UPDATE devices SET last_seen_at = now() WHERE id = :id"), {"id": row.id})
    return Device(row.id)


CurrentDevice = Annotated[Device, Depends(current_device)]
