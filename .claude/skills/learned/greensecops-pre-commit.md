# GreenSecOps: Pre-commit Hooks (prek)

**When to use:** Running linting/formatting checks manually, or installing hooks in a fresh clone.

## Tool

Uses `prek` (modern pre-commit alternative), not plain `pre-commit`.
Installed as a dev dependency in `backend/pyproject.toml` (shared across the uv workspace).

`prek` has native monorepo/workspace support: it auto-discovers every
`.pre-commit-config.yaml` in the repo and runs each as its own scoped
"project" (self-relative `files:` patterns, cwd set to that project's own
directory), in addition to the repo-root config. No manual wiring needed to
chain them together — a single `prek run` (or the installed git hook) runs
all of them. Confirm the discovered set with `uv run prek list`.

## Config layout

- `.pre-commit-config.yaml` (root) — workspace-wide only: file hygiene,
  OpenAPI client generation, landing example rendering, commit-msg linting
- `backend/.pre-commit-config.yaml` — ruff, ruff-format, mypy-backend, opa-fmt, opa-check
- `docs/.pre-commit-config.yaml` — ruff, ruff-format (scoped to `ext/`)
- `frontend/.pre-commit-config.yaml` — biome-check
- `action/.pre-commit-config.yaml` — biome-check-action, tsc-action, plus its own file
  hygiene + commit-msg subset (kept fully standalone since `action/` is subtree-synced
  to a public repo and must work with no root config present — this is also why it
  can't be merged into one of the other files, unlike the others its `files:` patterns
  are relative to itself, not the monorepo root)
- `landing/.pre-commit-config.yaml` — biome-check-landing

Each of the 5 project configs is independently runnable from inside its own
directory too, e.g. `cd backend && uv run prek run --all-files`.

## Install hooks into git (run once per clone)

```bash
cd backend
uv run prek install -f
# -f forces reinstall if a hook already exists
# Installs to: ../.git/hooks/pre-commit
```

## Run all hooks manually (all files)

```bash
# From repo root -- runs every discovered project's hooks
uv run prek run --all-files
```

## Run hooks on changed files only (like CI does)

```bash
uv run prek run --from-ref origin/main --to-ref HEAD --show-diff-on-failure
```

## Run one project's hooks, or a single hook

```bash
uv run prek list                # see every discovered project:hook id
uv run prek run backend --all-files       # every hook in backend/.pre-commit-config.yaml
uv run prek run backend:ruff --all-files  # just the ruff hook
```

## Hook stages

| Stage | Hooks |
|-------|-------|
| `pre-commit` (default) | file hygiene, generate-openapi-client, render-landing-examples, and every project's lint/format hooks |
| `pre-push` | mypy-backend (inside `backend/.pre-commit-config.yaml`) |
| `commit-msg` | conventional-pre-commit (root and inside `action/.pre-commit-config.yaml`) |

## Hook details

| Hook | Location | What it does |
|------|----------|---------------|
| `trailing-whitespace` | root | Strip trailing whitespace |
| `end-of-file-fixer` | root | Ensure files end with newline |
| `check-yaml` | root | Validate YAML (`--unsafe` allows custom tags in compose files) |
| `check-json` | root | Validate JSON (excludes `launch.json`, tsconfigs with comments) |
| `check-toml` | root | Validate TOML |
| `check-merge-conflict` | root | Block commits with conflict markers |
| `detect-private-key` | root | Block private key files |
| `check-added-large-files` | root | Block files >500KB |
| `mixed-line-ending` | root | Force LF endings |
| `generate-openapi-client` | root | Regenerate TypeScript client when backend Python files change |
| `render-landing-examples` | root | Regenerate landing-page workflow snippets from `examples/*.yml` |
| `conventional-pre-commit` | root | Enforce conventional commit message format |
| `ruff` / `ruff-format` | `backend/` | Python lint + format for `app/` |
| `mypy-backend` | `backend/` | Type check `app/` (pre-push only) |
| `opa-fmt` / `opa-check` | `backend/` | Format/validate `app/rules/*.rego` via Docker |
| `ruff` / `ruff-format` | `docs/` | Python lint + format for `ext/` |
| `biome-check` | `frontend/` | Lint+format TS/TSX/JS/JSON (excludes `src/client/`) |
| `biome-check-action` / `tsc-action` | `action/` | Lint+format+typecheck `src/` |
| `biome-check-landing` | `landing/` | Lint+format TS/JSON |

## Biome multi-root gotcha

`frontend/`, `action/`, and `landing/` are all bun workspace members, each with
its own `biome.json`. When their `biome check` invocations run close together
in one `prek` pass, biome's own workspace auto-discovery can misfire with
`Found a nested root configuration, but there's already a root configuration`.
Fix: always pass `--config-path=.` on these `bunx biome check` calls to force
explicit, non-scanning config resolution.

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
