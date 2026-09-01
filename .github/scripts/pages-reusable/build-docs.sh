#!/usr/bin/env bash
# Build the documentation site into docs/_build/html.
#
# -W matches docs/Dockerfile: a malformed rule METADATA block should fail the
# build, not ship a broken page. This is the only place the documentation is
# built in CI, so it is also the only gate on that.
#
# DOCS_BASE_URL comes from the calling step's env.
set -euo pipefail

uv sync --package docs
uv run sphinx-build -b html -W docs docs/_build/html
