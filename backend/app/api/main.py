"""The REST API (§8.6). Run with `uv run uvicorn app.api.main:app`."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api import devices, errors, geocode, health, places
from app.api.ratelimit import RateLimiter
from app.geocode.kartverket import KartverketClient
from app.settings import Settings, get_settings


def api_kartverket(settings: Settings, http: httpx.AsyncClient) -> KartverketClient:
    """Kartverket for the API: someone is waiting, so no retries and a short timeout."""
    return KartverketClient(
        http,
        settings.adresse_url,
        settings.stedsnavn_urls,
        retry_delays_s=(),
        timeout_s=settings.search_timeout_s,
        kommune_punkt_url=settings.kommune_punkt_url,
    )


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = create_async_engine(settings.database_url, pool_pre_ping=True)
        app.state.sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
        http = httpx.AsyncClient()
        app.state.kartverket = api_kartverket(settings, http)
        try:
            yield
        finally:
            await http.aclose()
            await engine.dispose()

    app = FastAPI(title="Kring API", version="1", lifespan=lifespan)
    app.state.settings = settings
    app.state.device_limiter = RateLimiter(settings.rate_limit_per_minute, 60)
    app.state.register_limiter = RateLimiter(settings.register_limit_per_hour, 3600)
    app.state.search_limiter = RateLimiter(settings.search_limit_per_minute, 60)
    errors.install(app)
    app.include_router(devices.router)
    app.include_router(health.router)
    app.include_router(places.router)
    app.include_router(geocode.router)
    return app


app = create_app()
