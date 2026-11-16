# Deploying Kring to Render

[`render.yaml`](../render.yaml) at the repo root is a Render Blueprint. It describes three resources, all in Frankfurt:

| Resource | Type | What it runs |
|---|---|---|
| `kring-api` | web service, `0.5c-512mb` | `uvicorn app.api.main:app` (the REST API, spec §8.6) |
| `kring-worker` | background worker, `0.5c-512mb` | `python -m app.worker` (polling, geocoding; later matching and push) |
| `kring-db` | Postgres 17, `0.1c-256mb`, 1 GB disk | PostGIS, created by the first migration |

These are the smallest paid instance types; Render renamed «starter». Prices are on Render's pricing page. Both services build from `backend/` with `uv sync --locked --no-dev`, and run `alembic upgrade head` as their pre-deploy command. The migrations take an advisory lock, so the two runs don't collide: one migrates, the other then finds the database at head.

## First deploy

1. Push the branch the Blueprint deploys (`m1` during M1):

   ```bash
   git push -u origin m1
   ```

2. In the Render dashboard: **New → Blueprint**, connect the GitHub repo, and pick branch `m1`. Render reads `render.yaml`, lists the three resources and asks you to confirm.
3. Wait for both services to go live. The database starts empty, so the worker's first cycle reads the last quarter from Politiloggen and geocodes every Oslo and Akershus thread. That takes a few minutes. Watch for its `ingest LastQuarter: …` log line.
4. Check it:

   ```bash
   curl -s https://<api-host>/v1/health
   ```

   It should return 200, with `last_success_at` under 2 minutes old. Before the first cycle has finished, it returns 503 `stale`. That is expected.

Render's own health check uses `/v1/health/live`, which only says the process is up. `/v1/health` would fail the first deploy, which happens before any poll, and it would restart the API whenever Politiloggen is down.

## Redeploying

A push to the Blueprint's branch redeploys both services (`autoDeployTrigger` defaults to `commit`). Changes outside `backend/` don't trigger a build. A change to `render.yaml` itself is applied by the Blueprint sync.

- **Web:** the new instance gets traffic once `/v1/health/live` answers. Then the old one is stopped.
- **Worker:** the new worker starts about 60 s before the old one gets SIGTERM. It logs `another worker holds the ingestion lock; waiting for it` and starts its first cycle once the old one has stopped (`KRING_WORKER_WAIT_FOR_LOCK=true`). A cycle that the SIGTERM interrupts is rolled back and redone by the new worker, so no cycle runs twice.
- The rate limits are kept in memory, so they reset on every API deploy.

After M1 is merged, change `branch: m1` to `branch: main` in `render.yaml` for both services.

## Rolling back

Dashboard → the service → **Events** → pick an earlier successful deploy → **Rollback**. Roll back both services if the bad change touched shared code.

A rollback doesn't undo migrations. So far every migration only adds things, so old code runs on the new schema. If a migration ever breaks old code, downgrade first from a shell on the worker (below), with `uv run --no-sync alembic downgrade <revision>`, and then roll back.

## Running a command on Render

Open a shell on the worker: dashboard → `kring-worker` → **Shell**, or with the Render CLI, `render ssh` and pick the worker. The environment, including the database URL, is the service's own. The shell closes when the service redeploys.

To re-geocode stored events after a geocoder change (spec §9.6, M1 step 1). This is a dry run, which prints every change:

```bash
uv run --no-sync python -m app.regeocode
```

To write the changes:

```bash
uv run --no-sync python -m app.regeocode --apply
```

It can run while the worker runs. It never sends pushes.

To print event counts and the poll status (the same script works locally, for comparison):

```bash
uv run --no-sync python -m scripts.db_counts
```

## Logs

Dashboard → the service → **Logs**. These lines matter:

- **Worker:**
  - `ingest LastDay: …` each cycle, every ~60 s.
  - `cycle crashed`, or an ERROR for no successful poll in 10 minutes.
  - The `waiting for` / `got the ingestion lock` pair during deploys.
- **API:** uvicorn's access log, one line per request. Unhandled errors are logged as `api: unhandled error` with a traceback, and returned to the client as a 500 `internal_error`.

## Connecting to the database from your machine

The database accepts no outside connections (`ipAllowList: []`), because places are personal data (§8.8). For a while:

1. Dashboard → `kring-db` → **Networking**: add your IP.
2. Connect with the **External Database URL** and `sslmode=require`.
3. Remove your IP again afterwards.

## Secrets

Nothing secret is in the repo. The database URL comes from the Blueprint (`fromDatabase`).

Push (M1 step 7): the worker sends for real on Render (`KRING_PUSH_DRY_RUN=false` in `render.yaml`). An Expo access token is only needed if «enhanced security for push» is turned on in the Expo project. If it is, add `KRING_EXPO_ACCESS_TOKEN` in the dashboard on `kring-worker`.

To see what was pushed and its status, run this in the worker shell:

```bash
uv run --no-sync python -m scripts.db_counts
```

## Known limits (M1)

- **One web instance.** The rate limits are per process and in memory. A shared limit is M4 (§14).
- **The registration limit can be dodged.** The per-IP limit on `POST /v1/devices` reads the client IP from `X-Forwarded-For` (`--forwarded-allow-ips '*'`), and a client can set that header itself. It slows down casual abuse, nothing more.
- **Python 3.12.16.** It is pinned with `PYTHON_VERSION`, because Render's default is 3.14 and the project needs 3.12. If Render doesn't have that patch release, the build fails at once. Set another 3.12.x in `render.yaml` if so.
