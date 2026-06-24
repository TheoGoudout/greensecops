# GreenSecOps: Backend Test Cycle

**When to use:** Running backend tests locally or verifying before push.

## Prerequisites

DB and Redis must be running. Either use docker compose or run containers manually:

```bash
docker compose up -d db redis mailcatcher
```

## Run migrations + seed data first

```bash
cd backend
uv run bash scripts/prestart.sh
# Runs: backend_pre_start.py (wait for DB) → alembic upgrade head → initial_data.py (seed superuser)
```

## Run tests with coverage

```bash
cd backend
uv run bash scripts/tests-start.sh "My coverage title"
# Runs: app/tests_pre_start.py → coverage run -m pytest tests/ → coverage report → coverage html
```

Or run manually step by step:

```bash
cd backend
uv run coverage run -m pytest tests/
uv run coverage report
uv run coverage html --title "local"
```

## Coverage threshold

CI enforces **90%** minimum:

```bash
cd backend
uv run coverage report --fail-under=90
```

HTML report lands in `backend/htmlcov/`.

## Run a specific test file or test

```bash
cd backend
uv run pytest tests/api/routes/test_analyses.py -v
uv run pytest tests/ -k "test_name_substring" -v
```

## Coverage omits (pyproject.toml)

These files are excluded from coverage tracking and do not count against the threshold:
- `app/initial_data.py`
- `app/backend_pre_start.py`
- `app/tests_pre_start.py`
- `app/services/llm/*`
- `app/services/github/app_client.py`
- `app/services/github/fix_delivery.py`
- `app/workers/tasks/fix_generation.py`
- `app/workers/tasks/fix_delivery.py`
- `app/services/opa/evaluator.py`

## Conftest fixtures

- `db` — session-scoped, calls `init_db()`, real PostgreSQL
- `client` — module-scoped `TestClient`
- `superuser_token_headers` — module-scoped
- `normal_user_token_headers` — module-scoped

**Never mock the database.** Tests use real PostgreSQL; mocking caused prod divergence historically.

## Test file locations

```
backend/tests/
├── api/routes/          # API endpoint tests (one file per route module)
├── crud/                # CRUD layer tests
├── services/            # Service layer tests (badge, dedup, OPA, scoring, webhook)
├── workers/tasks/       # Celery task tests
├── scripts/             # Pre-start script tests
└── utils/               # Test helpers (user.py, utils.py)
```

## CI equivalent (what GitHub Actions does)

```bash
docker compose up -d db mailcatcher
cd backend
uv run bash scripts/prestart.sh
uv run bash scripts/tests-start.sh "Coverage for $SHA"
uv run coverage report --fail-under=90
```
