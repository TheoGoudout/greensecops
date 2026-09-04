#!/usr/bin/env bash
# The generate-openapi-client hook imports the backend app, which instantiates
# Settings and therefore needs the required env vars.
set -euo pipefail

.github/scripts/shared/prepare-env-files.sh
# FIRST_SUPERUSER_PASSWORD is required but left empty in the example
# (env_ignore_empty drops empty values), so give it a non-empty value.
printf '\nFIRST_SUPERUSER_PASSWORD=ci-not-a-real-password\n' >> .env
