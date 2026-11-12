# stedSafe backend

FastAPI + PostgreSQL/PostGIS. Spec: [`../docs/stedSafe-spec.md`](../docs/stedSafe-spec.md) §8–9. Current plan: [`../docs/plans/m0.md`](../docs/plans/m0.md).

## Local setup (macOS, no Docker)

```bash
brew install postgresql@17 postgis uv
```

```bash
cd backend && uv sync
```

`uv` downloads and pins Python 3.12 for this project, whatever the system Python is.

### Database

Homebrew's PostGIS is built for Postgres 17 and 18, not 16, so the project uses 17. Start the server as a plain background process (it stops at reboot; use `brew services start postgresql@17` instead if you want it at login):

```bash
LC_ALL=en_US.UTF-8 /opt/homebrew/opt/postgresql@17/bin/pg_ctl -D /opt/homebrew/var/postgresql@17 -l /opt/homebrew/var/log/postgresql@17.log -w start
```

Create the dev and test databases (once):

```bash
/opt/homebrew/opt/postgresql@17/bin/createdb stedsafe && /opt/homebrew/opt/postgresql@17/bin/createdb stedsafe_test
```

Apply migrations to the dev database (the tests rebuild `stedsafe_test` themselves):

```bash
uv run alembic upgrade head
```

Migrations are hand-written SQL in `alembic/versions/`, taken from spec §8.4; there is no autogenerate. The test database URL can be changed with `STEDSAFE_TEST_DATABASE_URL`.

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
