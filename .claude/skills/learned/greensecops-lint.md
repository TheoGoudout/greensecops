# GreenSecOps: Lint & Type Check

**When to use:** Before committing, after editing Python or TypeScript files, or when CI lint fails.

## Python (backend)

All commands run from `backend/` with `uv run`:

```bash
cd backend

# Lint (auto-fix)
uv run ruff check app --fix

# Format (auto-fix)
uv run ruff format app

# Lint check only (no fix — for CI-style verification)
uv run ruff check app
uv run ruff format app --check

# Type checking (both tools used in this project)
uv run mypy app --ignore-missing-imports
uv run ty check app

# All at once (matches backend/scripts/lint.sh)
uv run mypy app && uv run ty check app && uv run ruff check app && uv run ruff format app --check
```

Ruff config in `backend/pyproject.toml`:
- Rules: E, W, F, I (isort), B (bugbear), C4, UP (pyupgrade), ARG001, T201 (no print)
- Excludes: `alembic/` directory
- `tests/**` ignores ARG001

## Frontend

From `frontend/`:

```bash
cd frontend

# Lint + format (auto-fix, matches pre-commit hook)
bunx biome check --write --unsafe --no-errors-on-unmatched --files-ignore-unknown=true ./

# Or via package.json script
bun run lint

# Type check only
bun run typecheck   # runs: tsc --noEmit
```

Biome config: `frontend/biome.json`
- Excludes: `dist/`, `node_modules/`, `src/routeTree.gen.ts`, `src/client/**/*`, `src/components/ui/**/*`, playwright files
- Formatter: spaces, double quotes, no semicolons

## Action

From `action/`:

```bash
cd action

# Lint + format
bunx biome check --write --unsafe --no-errors-on-unmatched --files-ignore-unknown=true src/

# Type check
bunx tsc --noEmit
```

## OPA policies

Requires Docker:

```bash
# Format rego files in-place
docker run --rm -v "$(pwd)/backend/app/rules:/policies" openpolicyagent/opa:latest-static fmt --write /policies

# Validate rego files
docker run --rm -v "$(pwd)/backend/app/rules:/policies:ro" openpolicyagent/opa:latest-static check /policies
```

## Quick full-project lint (no type check)

```bash
cd backend && uv run ruff check app --fix && uv run ruff format app && cd ..
cd frontend && bun run lint && cd ..
cd action && bunx biome check --write --unsafe --no-errors-on-unmatched --files-ignore-unknown=true src/ && cd ..
```

## What pre-commit (prek) runs automatically

On commit: ruff lint+format, biome (frontend), biome+tsc (action), OPA fmt+check, OpenAPI client generation
On push (pre-push stage): mypy for `backend/app/`
On commit-msg: conventional commits enforcement
