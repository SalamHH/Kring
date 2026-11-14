# stedSafe backend

FastAPI + PostgreSQL/PostGIS. Spec: [`../docs/stedSafe-spec.md`](../docs/stedSafe-spec.md) §8–9. Current plan: [`../docs/plans/m1.md`](../docs/plans/m1.md).

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

## Running the worker

The ingestion worker polls Politiloggen every 60 s, geocodes new and changed threads, and writes to the dev database. Stop it with Ctrl-C; a cycle in progress is rolled back. Only one worker can run per database (Postgres advisory lock). A second one exits at once, unless `STEDSAFE_WORKER_WAIT_FOR_LOCK=true`, which makes it wait for the lock (used on Render; see [`../docs/deploy.md`](../docs/deploy.md)).

```bash
uv run python -m app.worker
```

On an empty database the first cycle reads the last quarter (about 100 pages) and geocodes every Oslo and Akershus thread, which takes a few minutes. Later cycles read `LastDay` and take a second or two.

## Running the API

The REST API (spec §8.6) on http://127.0.0.1:8000, using the same dev database:

```bash
uv run uvicorn app.api.main:app --reload
```

Interactive docs are at `/docs`. `GET /v1/health` returns 503 until the worker has polled successfully in the last 10 minutes. Rate limits are kept in memory, so they reset when the server restarts.

## Re-geocoding stored events

After a geocoder change (a ranking, an alias, a new rule), stored events keep their old placement until their thread changes. Re-run the geocoder and classifier over them (spec §9.6). It is a dry run by default and prints every change:

```bash
uv run python -m app.regeocode
```

```bash
uv run python -m app.regeocode --apply
```

Filters: `--since 2026-11-01`, `--kommune 0301,3201`, `--method kommune,none` (`none` = the last geocode failed), `--ids <id>,<id>`. It never sends pushes. It can run while the worker is running: events the worker changes in the meantime are skipped and reported, so run it again to pick them up. A dry run writes nothing to `events`, but it does fill the geocode cache.

## M0 report data

Replays the recorded quarter offline and writes `docs/m0/replay-tables.md` and the 25-street review page `docs/m0/street-sample.html`:

```bash
uv run python -m scripts.m0_report
```

## Settings

Read from environment variables prefixed `STEDSAFE_` or from `backend/.env` (git-ignored). See `app/settings.py`. For example:

```bash
STEDSAFE_DATABASE_URL=postgresql+asyncpg://localhost/stedsafe
STEDSAFE_ALLOWED_FYLKER='["03","32"]'
```

## Layout

All the §8.9 modules live under the `app` package: `app/api`, `app/ingest`, `app/geocode`, `app/classify`, `app/match`, `app/notify`, `app/digest`, `app/db`, plus `app/settings.py`. Tests and recorded fixtures are in `tests/` (`tests/fixtures/politiloggen`, `tests/fixtures/kartverket`).

## Recorded Kartverket responses

Geocoder tests run offline against responses in `tests/fixtures/kartverket/`, recorded by running the reference script (`research/presisjonstest.py`) over the Appendix C inputs in `tests/appendix_c.py`. To fill in missing recordings, or to re-record everything:

```bash
uv run python -m scripts.record_kartverket
```

```bash
uv run python -m scripts.record_kartverket --refresh
```

This calls the public Kartverket APIs. Transient errors (429/5xx) are never saved.

The port makes extra lookups the script never makes (`app/geocode/tillegg.py`). Record those by running the port itself over the recorded threads:

```bash
uv run python -m scripts.record_kartverket --port
```

To record responses for the recorded Oslo and Akershus Politiloggen threads (step 6 parity, step 9 replay), each geocoded in its own municipality. Responses that are already recorded are replayed, not requested again. All of them are stored together in `tests/fixtures/kartverket/threads.jsonl.gz`:

```bash
uv run python -m scripts.record_kartverket --threads
```

## Recorded Politiloggen responses

`tests/fixtures/politiloggen/` holds the kommuneinfo municipality list, one raw `/messagethreads` page, and every Oslo and Akershus thread from a `LastQuarter` fetch (`quarter.json`). `district_notices.json` holds every district-wide notice («Oslo politidistrikt» in the municipality field) from a `LastQuarter` fetch, nationwide. Re-record only that file with `uv run python -m scripts.record_politiloggen --notices`. To re-record them (re-record the Kartverket thread responses afterwards):

```bash
uv run python -m scripts.record_politiloggen
```
