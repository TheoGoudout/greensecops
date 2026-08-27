# GreenSecOps: E2E Tests (Playwright)

**When to use:** Testing frontend user flows after UI or API changes.

## Test location

`frontend/tests/` — Chromium only (Firefox/Safari commented out in config)

| File | What it tests |
|------|--------------|
| `login.spec.ts` | Login form |
| `sign-up.spec.ts` | Signup flow |
| `reset-password.spec.ts` | Password reset via email |
| `user-settings.spec.ts` | Profile settings |
| `admin.spec.ts` | Admin user management |
| `golden-path.spec.ts` | Repo → analysis → issue → fix (mocked API) |
| `auth.setup.ts` | Auth state setup (runs first, saves to `playwright/.auth/user.json`) |

## Option 1: Local (dev server auto-starts)

Requires: `docker compose up -d db redis mailcatcher backend` already running.

```bash
cd frontend
bunx playwright test                        # headless
bunx playwright test --ui                   # interactive UI mode
bunx playwright test tests/login.spec.ts    # single file
bunx playwright test -k "login page"        # by test name
```

`playwright.config.ts` auto-starts `bun run dev` if no server is listening on `:5173`.

## Option 2: Full docker stack (production-like, matches CI)

```bash
# From repo root
bash scripts/generate-client.sh          # ensure client is up to date
docker compose build
docker compose down -v --remove-orphans

docker compose run --rm playwright \
  bunx playwright test \
  --fail-on-flaky-tests \
  --trace=retain-on-failure

docker compose down -v --remove-orphans
```

Reports go to `frontend/blob-report/` and `frontend/test-results/`.

## Sharded run (matches CI exactly)

```bash
docker compose run --rm playwright \
  bunx playwright test \
  --fail-on-flaky-tests \
  --trace=retain-on-failure \
  --shard=1/4
```

## View reports

```bash
cd frontend
bunx playwright show-report              # opens HTML report in browser
```

## Auth state

`auth.setup.ts` runs before all tests and writes auth cookies to `playwright/.auth/user.json`.
Tests in the `chromium` project depend on `setup` project and inherit this state.

Tests that need no auth (login/signup pages) override with:

```typescript
test.use({ storageState: { cookies: [], origins: [] } })
```

## Env vars needed (from `.env`)

```
FIRST_SUPERUSER=admin@example.com
FIRST_SUPERUSER_PASSWORD=testpassword
MAILCATCHER_HOST=http://localhost:1080   # for email tests
VITE_API_URL=http://localhost:8000
```

Playwright docker service reads `.env` directly via `env_file: .env`.

## API mocking pattern (golden-path tests)

```typescript
await page.route("**/api/v1/repositories**", (route) => {
  route.fulfill({ json: MOCK_DATA })
})
```

Golden-path tests mock the API entirely. Login/admin/settings tests hit the real backend.

## CI behavior

- 4 parallel shards via matrix strategy
- `--fail-on-flaky-tests` — flaky tests fail the build
- `--trace=retain-on-failure` — traces kept on failure
- Blob reports uploaded per shard, merged into HTML report artifact (30-day retention)
- `workers: process.env.CI ? 1 : undefined` — single worker in CI
