"""The REST API (§8.6). Run with `uv run uvicorn app.api.main:app`."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api import devices, errors, health
from app.api.ratelimit import RateLimiter
from app.settings import Settings, get_settings


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = create_async_engine(settings.database_url, pool_pre_ping=True)
        app.state.sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
        try:
            yield
        finally:
            await engine.dispose()

    app = FastAPI(title="stedSafe API", version="1", lifespan=lifespan)
    app.state.settings = settings
    app.state.device_limiter = RateLimiter(settings.rate_limit_per_minute, 60)
    app.state.register_limiter = RateLimiter(settings.register_limit_per_hour, 3600)
    errors.install(app)
    app.include_router(devices.router)
    app.include_router(health.router)
    return app


app = create_app()
