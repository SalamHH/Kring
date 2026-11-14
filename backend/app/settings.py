"""Runtime settings, read from environment variables prefixed KRING_ (or backend/.env)."""

from __future__ import annotations

from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="KRING_", env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://localhost/kring"
    # On Render a new worker starts before the old one is stopped; it waits for the lock
    # instead of exiting (decided 2026-11-14). Locally a second worker exits at once.
    worker_wait_for_lock: bool = False

    @field_validator("database_url")
    @classmethod
    def _asyncpg_url(cls, v: str) -> str:
        """Render gives postgresql://user:pw@host/db (or postgres://). SQLAlchemy needs the
        asyncpg driver named in the scheme."""
        for prefix in ("postgres://", "postgresql://"):
            if v.startswith(prefix):
                return "postgresql+asyncpg://" + v[len(prefix) :]
        return v

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
    kommune_punkt_url: str = "https://ws.geonorge.no/kommuneinfo/v1/punkt"
    stedsnavn_urls: list[str] = [
        "https://ws.geonorge.no/stedsnavn/v1/navn",
        "https://api.kartverket.no/stedsnavn/v1/navn",
    ]

    # API (§8.6, §8.8). The rate limits are kept in memory: one web instance in M1 (§14 M4
    # moves to a shared limit). A device may make rate_limit_per_minute requests a minute;
    # registrations are limited per client IP, since there is no device yet.
    rate_limit_per_minute: int = 120
    register_limit_per_hour: int = 20
    # Geocode search (§8.6): per device, on top of the general limit. Kartverket is called
    # without retries and with a short timeout, since someone is typing.
    search_limit_per_minute: int = 30
    search_timeout_s: float = 5.0
    search_cache_max_age_days: int = 30
    places_per_device: int = 10  # D10
    # Push (§6.2, §8.7; M1 step 7). Dry run logs each push instead of sending it; Render turns
    # it off. The access token is only needed if «enhanced security» is on in the Expo project.
    push_dry_run: bool = True
    expo_access_token: str | None = None
    expo_push_url: str = "https://exp.host/--/api/v2/push/send"
    expo_receipts_url: str = "https://exp.host/--/api/v2/push/getReceipts"
    push_max_age_min: int = 30  # first message at most this old at detection
    push_daily_limit: int = 3  # pushes per place per calendar day in the device's tz
    # An event the notifier first sees this long after it was stored (the worker was down between
    # ingest and notify) is marked handled without a push.
    push_late_after_s: int = 600
    receipt_delay_s: int = 15 * 60
    receipt_give_up_s: int = 24 * 3600  # Expo keeps receipts for about a day
    # GET /v1/health returns 503 when the last successful poll is older than this (§8.3).
    health_stale_after_s: int = 10 * 60

    def kommune_allowed(self, kommunenummer: str | None) -> bool:
        return bool(kommunenummer) and kommunenummer[:2] in self.allowed_fylker


@lru_cache
def get_settings() -> Settings:
    return Settings()
