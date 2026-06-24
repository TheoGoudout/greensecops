# GreenSecOps: DB Migration (Alembic)

**When to use:** Adding, renaming, or removing DB columns/tables after modifying SQLModel models.

## Setup

- Config: `backend/alembic.ini` → `script_location = app/alembic`
- Versions: `backend/app/alembic/versions/`
- Models registered in `env.py` via `import app.models` + `target_metadata = SQLModel.metadata`
- DB URL read from `settings.SQLALCHEMY_DATABASE_URI` at runtime

## Naming convention

Files use sequential numeric prefix: `0001_`, `0002_`, ... `000N_`
**Not** timestamp-based. Check the latest version number first:

```bash
ls backend/app/alembic/versions/
```

## Create a new migration (autogenerate from model diff)

DB must be running and already at current head before autogenerating:

```bash
docker compose up -d db
cd backend
uv run bash scripts/prestart.sh   # apply existing migrations first

# Generate migration from model changes
uv run alembic revision --autogenerate -m "short_description_of_change"
```

Alembic generates a file with a random revision ID. **Rename it** to follow the numbering:

```bash
# Example: rename f3a9bc12.py → 0008_short_description_of_change.py
# Then update inside the file:
#   revision = "0008"
#   down_revision = "0007"   (previous revision)
```

Always review the generated file — autogenerate misses: index changes on existing columns, server defaults, check constraints, and anything ORM-level only.

## Apply migrations

```bash
cd backend
uv run alembic upgrade head      # apply all pending migrations
uv run alembic upgrade +1        # apply exactly one migration
```

## Downgrade

```bash
cd backend
uv run alembic downgrade -1      # roll back one migration
uv run alembic downgrade 0006    # roll back to specific revision
```

## Check current state

```bash
cd backend
uv run alembic current           # show current DB revision
uv run alembic history           # show full migration history
```

## Migration file structure

```python
"""Short description of change

Revision ID: 0008
Revises: 0007
Create Date: YYYY-MM-DD

"""

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("table_name", sa.Column("col", sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column("table_name", "col")
```

## prestart.sh (applied at startup)

```
backend_pre_start.py   → waits for DB to be ready
alembic upgrade head   → applies all pending migrations
initial_data.py        → seeds first superuser
```

This runs automatically in the `prestart` docker compose service and in CI before tests.

## Do NOT

- Create migration files manually without autogenerate unless necessary (schema drift risk)
- Edit already-applied migrations (create a new one instead)
- Skip the rename step — CI and other devs rely on sequential ordering for clarity
