FROM python:3.14-slim AS builder

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
# The reference-workflow doc page is generated from the canonical example file.
COPY examples/ examples/

ARG DOCS_BASE_URL=""
ENV DOCS_BASE_URL=${DOCS_BASE_URL}

RUN uv run sphinx-build -b html -W docs docs/_build/html


FROM nginx:1.31-alpine

COPY docs/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=builder /build/docs/_build/html /usr/share/nginx/html
