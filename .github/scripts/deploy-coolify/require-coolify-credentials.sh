#!/usr/bin/env bash
# Fail the run when the environment is missing its Coolify secrets.
#
# Checked in a step rather than through a workflow-level `env` boolean (the
# release-prepare.yml idiom) because these secrets live on the GitHub
# Environment, and environment secrets only resolve inside a job that declares
# `environment:`.
#
# A failure rather than a skip: a backend that silently did not deploy is a
# frontend talking to the wrong API.
#
# COOLIFY_URL, COOLIFY_API_TOKEN, COOLIFY_APP_UUID and ENVIRONMENT come from the
# calling step's env.
set -euo pipefail

MISSING=""
[ -n "$COOLIFY_URL" ] || MISSING="$MISSING COOLIFY_URL"
[ -n "$COOLIFY_API_TOKEN" ] || MISSING="$MISSING COOLIFY_API_TOKEN"
[ -n "$COOLIFY_APP_UUID" ] || MISSING="$MISSING COOLIFY_APP_UUID"

if [ -n "$MISSING" ]; then
  echo "::error::Missing Coolify secrets on the '${ENVIRONMENT}' environment:${MISSING}. See deployment.md."
  exit 1
fi
