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

    # Which municipalities to ingest and geocode, by fylkesnummer (first two digits of
    # the kommunenummer). M0 scope: Oslo (03, i.e. 0301) and Akershus (32).
    allowed_fylker: list[str] = ["03", "32"]

    # Kartverket (§9.2, §9.4). Place-name URLs are tried in order, as in the reference script.
    adresse_url: str = "https://ws.geonorge.no/adresser/v1/sok"
    stedsnavn_urls: list[str] = [
        "https://ws.geonorge.no/stedsnavn/v1/navn",
        "https://api.kartverket.no/stedsnavn/v1/navn",
    ]

    def kommune_allowed(self, kommunenummer: str | None) -> bool:
        return bool(kommunenummer) and kommunenummer[:2] in self.allowed_fylker


@lru_cache
def get_settings() -> Settings:
    return Settings()
