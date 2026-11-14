"""Settings: Render's database URL is turned into an asyncpg one."""

from __future__ import annotations

import pytest

from app.settings import Settings


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ("postgresql://u:p@dpg-x-a/stedsafe", "postgresql+asyncpg://u:p@dpg-x-a/stedsafe"),
        ("postgres://u:p@dpg-x-a:5432/stedsafe", "postgresql+asyncpg://u:p@dpg-x-a:5432/stedsafe"),
        ("postgresql+asyncpg://localhost/stedsafe", "postgresql+asyncpg://localhost/stedsafe"),
    ],
)
def test_database_url_uses_asyncpg(given: str, expected: str) -> None:
    assert Settings(database_url=given).database_url == expected
