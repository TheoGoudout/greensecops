# GreenSecOps: Generate OpenAPI TypeScript Client

**When to use:** After adding, removing, or changing any FastAPI route, request/response model, or endpoint signature.

## What it does

1. Imports the FastAPI app and dumps the OpenAPI schema to `openapi.json`
2. Runs `openapi-ts` to generate TypeScript client for `frontend/src/client/`
3. Runs `openapi-ts` again to generate TypeScript client for `action/src/client/`
4. Fixes trailing whitespace + missing EOF newlines left by openapi-ts (so pre-commit passes)

## Run

From repo root:

```bash
bash scripts/generate-client.sh
```

Requires:
- `uv` available (backend deps installed in `backend/.venv`)
- `bun` available (frontend deps installed)
- `.env` file present with `FIRST_SUPERUSER_PASSWORD` set (Settings loads at import time)

If `.env` is missing or incomplete:

```bash
cp .env.example .env
echo "FIRST_SUPERUSER_PASSWORD=local-dev" >> .env
bash scripts/generate-client.sh
```

## Output files (never hand-edit)

```
frontend/src/client/
├── sdk.gen.ts       # API methods
├── types.gen.ts     # Request/response types
├── schemas.gen.ts   # JSON schemas
└── core/            # Base HTTP client

action/src/client/
├── sdk.gen.ts
├── types.gen.ts
├── schemas.gen.ts
└── core/
```

These directories are excluded from biome linting and must never be hand-edited.

## This runs automatically on commit

The `generate-openapi-client` pre-commit hook runs `scripts/generate-client.sh` whenever any `backend/app/**/*.py` file is staged. If the hook changes client files, re-stage and recommit:

```bash
git add frontend/src/client/ action/src/client/
git commit
```

## Verify client is in sync with backend

```bash
bash scripts/generate-client.sh
git diff --name-only frontend/src/client/ action/src/client/
# Empty output = client already up to date
```

## Config files

- `frontend/openapi-ts.config.ts` — controls frontend client generation
- `action/openapi-ts.config.ts` — controls action client generation
