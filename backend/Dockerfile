# ---- builder ----
# Ref: https://docs.astral.sh/uv/guides/integration/docker/#multi-stage-builds
# Pinned by digest, not just by tag: `python` republishes 3.14.6-slim on every
# base-OS patch, so the tag alone does not make the build reproducible.
# Dependabot updates the digest alongside the tag (see .github/dependabot.yml).
FROM python:3.14.7-slim@sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 AS builder

# Install git
# Used for dependencies specified by Git URLs
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*

# Install uv
# Ref: https://docs.astral.sh/uv/guides/integration/docker/#installing-uv
COPY --from=ghcr.io/astral-sh/uv:0.9.26 /uv /uvx /bin/

ENV PYTHONUNBUFFERED=1

# Compile bytecode
# Ref: https://docs.astral.sh/uv/guides/integration/docker/#compiling-bytecode
ENV UV_COMPILE_BYTECODE=1

# uv Cache
# Ref: https://docs.astral.sh/uv/guides/integration/docker/#caching
ENV UV_LINK_MODE=copy

WORKDIR /app/

# Install dependencies
# Ref: https://docs.astral.sh/uv/guides/integration/docker/#intermediate-layers
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-install-workspace --no-dev --package app

COPY ./backend/scripts /app/backend/scripts

COPY ./backend/pyproject.toml ./backend/alembic.ini /app/backend/

COPY ./backend/app /app/backend/app

# Sync the project
# Ref: https://docs.astral.sh/uv/guides/integration/docker/#intermediate-layers
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-dev --package app

# ---- runtime ----
FROM python:3.14.7-slim@sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6

LABEL org.opencontainers.image.source="https://github.com/TheoGoudout/greensecops"
LABEL org.opencontainers.image.licenses="MIT"

# Install curl for health checks
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1

# Place executables in the environment at the front of the path
# Ref: https://docs.astral.sh/uv/guides/integration/docker/#using-the-environment
ENV PATH="/app/.venv/bin:$PATH"

WORKDIR /app/

COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/backend /app/backend

# Run as an unprivileged user rather than root. The uid and gid are pinned
# because deploy/ansible chowns the host side of celery-beat's bind mount to
# them — a bind mount keeps the host's ownership, so the two have to agree.
RUN groupadd --gid 1000 appuser \
    && useradd --create-home --uid 1000 --gid 1000 appuser

# celery-beat's PersistentScheduler writes its cursor here, and both deployments
# mount storage over it. Creating the directory owned by appuser is what makes
# that writable: Docker seeds an empty named volume from the image path it
# covers, ownership included, and without the directory in the image it seeds
# one owned by root that the unprivileged process cannot write to. That was
# `PermissionError: '/var/lib/celery/celerybeat-schedule'` at every beat start.
RUN install --directory --owner=appuser --group=appuser --mode=0750 /var/lib/celery

USER appuser

WORKDIR /app/backend/

# Health of the *default* CMD below. The Celery roles run the same image with a
# different command and no HTTP listener, so compose.yml and
# deploy/ansible/vars/services.yml override this per service — celery-worker
# with `inspect ping`, celery-beat with a schedule-file check, and prestart with
# `disable: true` because a one-shot migration job has no steady state.
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD curl -fsS http://localhost:8000/api/v1/system/health || exit 1

CMD ["fastapi", "run", "--workers", "4", "app/main.py"]
