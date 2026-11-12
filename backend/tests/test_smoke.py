import importlib

import pytest

from app.settings import Settings

SUBPACKAGES = ["api", "ingest", "geocode", "classify", "match", "notify", "digest", "db"]


@pytest.mark.parametrize("name", SUBPACKAGES)
def test_subpackages_import(name: str) -> None:
    importlib.import_module(f"app.{name}")


def test_settings_defaults() -> None:
    s = Settings()
    assert s.poll_interval_s == 60
    assert s.database_url.startswith("postgresql+asyncpg://")


@pytest.mark.parametrize(
    ("knr", "allowed"),
    [
        ("0301", True),
        ("3201", True),
        ("3207", True),
        ("3301", False),
        ("4601", False),
        (None, False),
        ("", False),
    ],
)
def test_kommune_allowed(knr: str | None, allowed: bool) -> None:
    assert Settings().kommune_allowed(knr) is allowed


def test_settings_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STEDSAFE_ALLOWED_FYLKER", '["03"]')
    assert Settings().kommune_allowed("3201") is False
