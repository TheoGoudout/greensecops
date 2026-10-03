#!/usr/bin/env bash
# Put the .env files in place for the local development stack, with the
# superuser password aligned with SERVICE_PASSWORD_FIRSTSUPERUSER.
#
# compose.override.yml takes FIRST_SUPERUSER_PASSWORD from .env, where the
# committed example leaves it empty — and the backend's settings refuse to
# start without one, so prestart would exit before running a migration. The
# Playwright job does the same in its own prepare-env-files.sh.
#
# SERVICE_PASSWORD_FIRSTSUPERUSER comes from the job's env.
set -euo pipefail

.github/scripts/shared/prepare-env-files.sh
printf '\nFIRST_SUPERUSER_PASSWORD=%s\n' "$SERVICE_PASSWORD_FIRSTSUPERUSER" >> .env
