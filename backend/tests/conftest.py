"""Shared test fixtures.

Database tests run against a separate database (default: stedsafe_test on localhost,
override with STEDSAFE_TEST_DATABASE_URL). The schema is rebuilt from the Alembic
migrations once per session, and every test runs inside a transaction that is rolled back.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

BACKEND_DIR = Path(__file__).resolve().parents[1]
TEST_DATABASE_URL = os.environ.get(
    "STEDSAFE_TEST_DATABASE_URL", "postgresql+asyncpg://localhost/stedsafe_test"
)


def alembic_config(url: str = TEST_DATABASE_URL) -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)
    cfg.attributes["configure_logger"] = False
    return cfg


@pytest.fixture(scope="session")
def migrated_db() -> str:
    """Rebuild the test schema from scratch: downgrade to base, then upgrade to head."""
    cfg = alembic_config()
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    return TEST_DATABASE_URL


@pytest.fixture
async def db(migrated_db: str) -> AsyncIterator[AsyncConnection]:
    """A connection inside a transaction that is always rolled back."""
    engine = create_async_engine(migrated_db, poolclass=pool.NullPool)
    async with engine.connect() as conn:
        trans = await conn.begin()
        try:
            yield conn
        finally:
            await trans.rollback()
    await engine.dispose()
