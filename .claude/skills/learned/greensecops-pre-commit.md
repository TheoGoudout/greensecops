# GreenSecOps: Pre-commit Hooks (prek)

**When to use:** Running linting/formatting checks manually, or installing hooks in a fresh clone.

## Tool

Uses `prek` (modern pre-commit alternative), not plain `pre-commit`.
Installed as a dev dependency in `backend/pyproject.toml`.

## Install hooks into git (run once per clone)

```bash
cd backend
uv run prek install -f
# -f forces reinstall if a hook already exists
# Installs to: ../.git/hooks/pre-commit
```

## Run all hooks manually (all files)

```bash
# From repo root
cd backend && uv run prek run --all-files
```

## Run hooks on changed files only (like CI does)

```bash
cd backend
uv run prek run --from-ref origin/main --to-ref HEAD --show-diff-on-failure
```

## Run a specific hook

```bash
cd backend
uv run prek run ruff
uv run prek run ruff-format
uv run prek run biome-check
uv run prek run mypy-backend
uv run prek run generate-openapi-client
uv run prek run opa-fmt
uv run prek run opa-check
```

## Hook stages

| Stage | Hooks |
|-------|-------|
| `pre-commit` (default) | file hygiene, ruff, ruff-format, biome (frontend), biome+tsc (action), OPA fmt+check, generate-openapi-client |
| `pre-push` | mypy-backend |
| `commit-msg` | conventional-pre-commit |

## Hook details

| Hook | What it does |
|------|-------------|
| `trailing-whitespace` | Strip trailing whitespace |
| `end-of-file-fixer` | Ensure files end with newline |
| `check-yaml` | Validate YAML (`--unsafe` allows custom tags in compose files) |
| `check-json` | Validate JSON (excludes `launch.json`, tsconfigs with comments) |
| `check-toml` | Validate TOML |
| `check-merge-conflict` | Block commits with conflict markers |
| `detect-private-key` | Block private key files |
| `check-added-large-files` | Block files >500KB |
| `mixed-line-ending` | Force LF endings |
| `ruff` | Python lint + autofix (`backend/` and `docs/ext/`) |
| `ruff-format` | Python format (`backend/` and `docs/ext/`) |
| `mypy-backend` | Type check `backend/app/` (pre-push only) |
| `generate-openapi-client` | Regenerate TypeScript client when Python files change |
| `biome-check` | Lint+format `frontend/` TS/TSX/JS/JSON (excludes `src/client/`) |
| `biome-check-action` | Lint+format `action/src/` |
| `tsc-action` | TypeScript check `action/src/` |
| `opa-fmt` | Format `.rego` files via Docker |
| `opa-check` | Validate `.rego` files via Docker |
| `conventional-pre-commit` | Enforce conventional commit message format |

## Env vars needed for generate-openapi-client hook

The hook imports the backend app, which reads Settings. Needs at minimum:

```bash
# In .env at repo root:
FIRST_SUPERUSER_PASSWORD=any-non-empty-value
# Plus all other required Settings fields
```

If `.env` is missing: `cp .env.example .env && echo "FIRST_SUPERUSER_PASSWORD=local-dev" >> .env`

## After hooks auto-fix files

```bash
git add -A          # re-stage fixed files
git commit          # commit will now pass
```
