# Pinned by digest, not just by tag: `python` republishes 3.14-slim on every
# patch release, so the tag alone does not make the build reproducible.
FROM python:3.14-slim@sha256:ce40764625a4ff50df3548277632e7f96c4e77fe75fa848aae9885476e7df5a4 AS builder

WORKDIR /build

COPY --from=ghcr.io/astral-sh/uv:0.9.26 /uv /bin/

ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy
ENV PATH="/build/.venv/bin:$PATH"

RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-install-workspace --package docs

COPY docs/ docs/
COPY backend/app/rules/ backend/app/rules/
# rego_autodoc reads each rule's METADATA block through app.core.rego_metadata,
# shared with the backend seeder and the CI validators so the three cannot drift
# on what a METADATA block is. That module is deliberately stdlib-only — no app
# imports, no third-party ones — which is what lets this image take the single
# file plus its (empty) package markers rather than the backend and its
# dependency set. tests/core/test_rego_metadata.py enforces that constraint.
COPY backend/app/__init__.py backend/app/
COPY backend/app/core/__init__.py backend/app/core/rego_metadata.py backend/app/core/
# The reference-workflow doc page is generated from the canonical example file.
COPY examples/ examples/

ARG DOCS_BASE_URL=""
ENV DOCS_BASE_URL=${DOCS_BASE_URL}

RUN uv run sphinx-build -b html -W docs docs/_build/html


# nginx-unprivileged rather than the stock nginx image: it is the same upstream
# build with the cache, run and log directories already owned by uid 101, so the
# server runs unprivileged without a chown layer of our own. An unprivileged
# process cannot bind a port below 1024, which is why docs/nginx.conf listens on
# 8080 and the deployment's container port is 8080 rather than 80.
FROM nginxinc/nginx-unprivileged:1.31.4-alpine@sha256:d9083fe47768377ef55dedafd67d4da7c2f2bc2bece7554954f29359deb0dce9

LABEL org.opencontainers.image.source="https://github.com/TheoGoudout/greensecops"
LABEL org.opencontainers.image.licenses="MIT"

COPY docs/nginx.conf /etc/nginx/conf.d/default.conf
# --chown so the docroot belongs to the uid that serves it. sphinx-build runs as
# root in the builder stage, so without this the pages arrive root-owned and are
# only readable here because the builder's umask happened to leave them 0644: a
# generated file or a copied asset carrying a tighter mode would fail to open
# and 403. Ownership by uid 101 makes serving independent of the builder's modes.
COPY --chown=101:101 --from=builder /build/docs/_build/html /usr/share/nginx/html

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -fsS -o /dev/null http://localhost:8080/ || exit 1

# Inherited from the base image, but stated here so the shipped uid is visible
# in this file and survives a future base-image change.
USER 101
