"""Runtime settings, read from environment variables prefixed STEDSAFE_ (or backend/.env)."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="STEDSAFE_", env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://localhost/stedsafe"

    # Politiloggen (§8.3)
    politiloggen_url: str = "https://api.politiloggen.politiet.no/messagethreads"
    poll_interval_s: int = 60
    # Time window (decided 2026-11-12): LastDay normally (one page of ~130 threads, filtered
    # on lastMessageOn); LastQuarter while the last successful poll is older than
    # wide_window_after_s, so a long outage is caught up.
    politiloggen_time_span: str = "LastDay"
    politiloggen_wide_time_span: str = "LastQuarter"
    wide_window_after_s: int = 23 * 3600
    page_size: int = 100
    min_pages: int = 3
    # Stop-rule safety margin (§8.3, decided 2026-11-12): 15 minutes.
    poll_safety_margin_s: int = 15 * 60

    # Which municipalities to ingest and geocode, by fylkesnummer (first two digits of
    # the kommunenummer). M0 scope: Oslo (03, i.e. 0301) and Akershus (32).
    allowed_fylker: list[str] = ["03", "32"]

    # Kartverket (§9.2, §9.4). Place-name URLs are tried in order, as in the reference script.
    adresse_url: str = "https://ws.geonorge.no/adresser/v1/sok"
    kommuneinfo_url: str = "https://ws.geonorge.no/kommuneinfo/v1/kommuner"
    stedsnavn_urls: list[str] = [
        "https://ws.geonorge.no/stedsnavn/v1/navn",
        "https://api.kartverket.no/stedsnavn/v1/navn",
    ]

    def kommune_allowed(self, kommunenummer: str | None) -> bool:
        return bool(kommunenummer) and kommunenummer[:2] in self.allowed_fylker


@lru_cache
def get_settings() -> Settings:
    return Settings()
