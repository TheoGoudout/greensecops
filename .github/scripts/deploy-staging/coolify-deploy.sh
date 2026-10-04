#!/usr/bin/env bash
# Point the staging resource at this commit's image tag and queue a deploy.
#
# Unlike production, the resource's git ref is not touched: staging tracks `main`
# permanently, and it is the TAG variable rather than the checked-out tree that
# decides which image runs.
#
# COOLIFY_URL, COOLIFY_TOKEN, UUID and TAG come from the calling step's env.
set -euo pipefail

ROOT=$(cd -- "$(dirname -- "$0")/../../.." && pwd)
# shellcheck source=.github/scripts/lib/coolify.sh
. "${ROOT}/.github/scripts/lib/coolify.sh"

echo "Setting TAG=${TAG}"
coolify_upsert_env "${UUID}" TAG "${TAG}"

echo "Triggering the deploy"
deployment=$(coolify_trigger_deploy "${UUID}")
echo "deployment=${deployment}" >> "$GITHUB_OUTPUT"
echo "Deployment ${deployment} queued."
