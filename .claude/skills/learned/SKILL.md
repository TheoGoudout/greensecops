# GreenSecOps — Learned Skills Index

This file is loaded automatically by Claude Code at session start.
It tells Claude which skill files exist, what each covers, and when to reach for them.

## How to use

Read the relevant skill file before running the corresponding operation.
Each file contains exact commands, prerequisites, caveats, and CI equivalents.

## Skill Registry

| File | Covers | Trigger |
|------|--------|---------|
| [greensecops-backend-test.md](greensecops-backend-test.md) | pytest + coverage, fixtures, 90% threshold, CI equivalent | Running or fixing backend tests |
| [greensecops-db-migration.md](greensecops-db-migration.md) | Alembic autogenerate, review, apply, rollback | Any SQLModel model change |
| [greensecops-docker.md](greensecops-docker.md) | docker compose dev/prod lifecycle, image builds | Starting stack, building images |
| [greensecops-e2e.md](greensecops-e2e.md) | Playwright E2E tests, headed/CI modes, fixtures | UI or API route changes |
| [greensecops-generate-client.md](greensecops-generate-client.md) | OpenAPI → TypeScript client codegen via `hey-api` | Any FastAPI route/schema change |
| [greensecops-lint.md](greensecops-lint.md) | ruff, mypy, biome — backend and frontend lint/type-check | Before commit, after editing Python/TS |
| [greensecops-pre-commit.md](greensecops-pre-commit.md) | `prek` hook runner, install, manual run | Fresh clone setup, hook troubleshooting |
| [greensecops-pr.md](greensecops-pr.md) | Required PR label set, `check-labels` CI gate, which label to pick | Creating or editing a GitHub PR |

## Load order guidance

For a full feature cycle, read skills in this order:

1. `greensecops-db-migration.md` — if models changed
2. `greensecops-generate-client.md` — if routes/schemas changed
3. `greensecops-backend-test.md` — to run/fix backend tests
4. `greensecops-e2e.md` — to run/fix E2E tests
5. `greensecops-lint.md` — before committing
6. `greensecops-pre-commit.md` — if hooks fail or need setup
7. `greensecops-docker.md` — if stack needs restart or rebuild
8. `greensecops-pr.md` — when opening the PR
