#!/usr/bin/env bash
# Align the Coolify-generated secrets with their .env counterparts so the backend
# process (running outside Docker) sees consistent credentials.
#
# The SERVICE_* values come from the job's env, where they are given test values:
# Coolify generates them at deploy time, so they are empty in CI.
set -euo pipefail

.github/scripts/shared/prepare-env-files.sh
{
  printf '\nFIRST_SUPERUSER_PASSWORD=%s\n' "$SERVICE_PASSWORD_FIRSTSUPERUSER"
  printf 'POSTGRES_PASSWORD=%s\n' "$SERVICE_PASSWORD_POSTGRES"
  printf 'POSTGRES_USER=%s\n' "$SERVICE_USER_POSTGRES"
  printf 'SECRET_KEY=%s\n' "$SERVICE_PASSWORD_64_SECRETKEY"
} >> .env
