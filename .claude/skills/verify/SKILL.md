---
name: verify
description: Run the GreenSecOps app locally (no docker daemon needed) and drive the UI with Playwright to verify a change end-to-end.
---

# GreenSecOps: local end-to-end verification

Works in environments without a docker daemon (PostgreSQL 16 + Redis are
installed as system services).

## 1. Services + env

```bash
cp .env.example .env   # fill SECRET_KEY, FIRST_SUPERUSER_PASSWORD, POSTGRES_PASSWORD
service postgresql start && service redis-server start
su postgres -c "psql -c \"ALTER USER postgres PASSWORD '<POSTGRES_PASSWORD>';\" -c 'CREATE DATABASE greensecops;'"
cd backend && uv run bash scripts/prestart.sh   # migrations + superuser seed
```

`prestart.sh` needs only PostgreSQL: it waits for the DB, runs the
migrations and seeds the superuser. (It used to block for up to 5 minutes on
an S3-compatible endpoint via `storage_pre_start.py`; that object-storage
stack was never used by any code path and has been removed.)

If no docker daemon and no native postgres/redis services are available
either (this sandbox's actual state as of 2026-07-23, despite the "no
docker daemon needed" framing above — that assumption doesn't hold in
every environment this skill runs in), fall back to `docker run` throwaway
containers for Postgres + Redis on their default ports instead, matching
`.env`'s `POSTGRES_SERVER=localhost`/`POSTGRES_PORT=5432`/
`REDIS_URL=redis://localhost:6379/0`.

Gotcha: the backend test suite's conftest teardown **deletes all users** —
re-run `uv run python app/initial_data.py` after `pytest` to restore the
superuser before logging in.

## 2. Run the app

```bash
cd backend && uv run uvicorn app.main:app --port 8000 &   # API
cp frontend/.env.example frontend/.env
cd frontend && bun run dev &                               # UI on :5173
curl -s http://localhost:8000/api/v1/utils/health-check/   # → true
```

Celery tasks queue into Redis without a worker running — endpoints that
`.delay()` still return 202, queued fixes just stay `pending`.

## 3. Seed data

No GitHub App creds locally, so seed via the models (`Session(engine)` from
`app.core.db`): Organization → Repository (`is_accessible=True`,
`installation_id=1`) → WorkflowFile → Analysis (`status=completed`) → Issue
(`resolved_at=None`) → Fix. One Fix per workflow file (unique constraint).

## 4. Drive the UI

Playwright is hoisted to the repo-root `node_modules` (bun workspace); a
script outside the repo must import it by absolute path:

```js
import { chromium } from "/home/user/greensecops/node_modules/playwright/index.mjs"
const browser = await chromium.launch({ executablePath: "/opt/pw-browsers/chromium" })
```

If `/opt/pw-browsers/chromium` doesn't exist in this environment, find the
Playwright-managed binary instead — it's cached per-user, not repo-local:
`find ~/.cache/ms-playwright -maxdepth 2 -iname chrome -type f` (look under
a `chromium-*/chrome-linux64/` directory). Also double-check the repo path
in the import — `/home/user/greensecops` is a placeholder, not necessarily
this checkout's actual path.

Login flow: goto `/login`, fill `input[type="email"]` +
`input[placeholder="Password"]` with FIRST_SUPERUSER creds, submit, wait for
redirect off `/login`. Repo pages live at `/repositories/{repo_id}/<tab>`.
Toasts are sonner — assert with `page.waitForSelector("text=<toast text>")`.
