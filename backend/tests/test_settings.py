"""Settings: Render's database URL is turned into an asyncpg one."""

from __future__ import annotations

import pytest

from app.settings import Settings


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ("postgresql://u:p@dpg-x-a/kring", "postgresql+asyncpg://u:p@dpg-x-a/kring"),
        ("postgres://u:p@dpg-x-a:5432/kring", "postgresql+asyncpg://u:p@dpg-x-a:5432/kring"),
        ("postgresql+asyncpg://localhost/kring", "postgresql+asyncpg://localhost/kring"),
    ],
)
def test_database_url_uses_asyncpg(given: str, expected: str) -> None:
    assert Settings(database_url=given).database_url == expected
