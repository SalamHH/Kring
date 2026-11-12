# stedSafe backend

FastAPI + PostgreSQL/PostGIS. Spec: [`../docs/stedSafe-spec.md`](../docs/stedSafe-spec.md) §8–9. Current plan: [`../docs/plans/m0.md`](../docs/plans/m0.md).

## Local setup (macOS, no Docker)

```bash
brew install postgresql@16 postgis uv
```

```bash
cd backend && uv sync
```

`uv` downloads and pins Python 3.12 for this project, whatever the system Python is.

Database setup (`createdb`, PostGIS, migrations) is added in M0 step 2.

## Everyday commands

Run from `backend/`:

```bash
uv run pytest
```

```bash
uv run ruff check .
```

```bash
uv run ruff format .
```

## Settings

Read from environment variables prefixed `STEDSAFE_` or from `backend/.env` (git-ignored). See `app/settings.py`. For example:

```bash
STEDSAFE_DATABASE_URL=postgresql+asyncpg://localhost/stedsafe
STEDSAFE_ALLOWED_FYLKER='["03","32"]'
```

## Layout

All the §8.9 modules live under the `app` package: `app/api`, `app/ingest`, `app/geocode`, `app/classify`, `app/match`, `app/notify`, `app/digest`, `app/db`, plus `app/settings.py`. Tests and recorded fixtures are in `tests/` (`tests/fixtures/politiloggen`, `tests/fixtures/kartverket`).
