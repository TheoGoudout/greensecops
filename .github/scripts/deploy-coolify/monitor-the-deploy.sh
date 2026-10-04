#!/usr/bin/env bash
# Watch the deploy through to its conclusion.
#
# COOLIFY_URL, COOLIFY_TOKEN, TAG, DEPLOYMENT and ENVIRONMENT come from the
# calling step's env.
set -euo pipefail

ROOT=$(cd -- "$(dirname -- "$0")/../../.." && pwd)
# shellcheck source=.github/scripts/lib/coolify.sh
. "${ROOT}/.github/scripts/lib/coolify.sh"

result=0
coolify_monitor_deploy "${DEPLOYMENT}" "Coolify ${ENVIRONMENT} deploy" "${TAG}" || result=$?

case "${result}" in
  0)
    echo "Deployed ${TAG} to ${ENVIRONMENT} ✅"
    echo "${ENVIRONMENT} API deployed at \`${TAG}\`." >> "$GITHUB_STEP_SUMMARY"
    ;;
  2)
    echo "::error::Check Coolify — ${ENVIRONMENT} is not on ${TAG}, and the dashboard has NOT been published."
    exit 1
    ;;
  *)
    exit 1
    ;;
esac
