#!/usr/bin/env bash
# Watch the staging deploy through to its conclusion.
#
# COOLIFY_URL, COOLIFY_TOKEN, TAG and DEPLOYMENT come from the calling step's env.
set -euo pipefail

ROOT=$(cd -- "$(dirname -- "$0")/../../.." && pwd)
# shellcheck source=.github/scripts/lib/coolify.sh
. "${ROOT}/.github/scripts/lib/coolify.sh"

result=0
coolify_monitor_deploy "${DEPLOYMENT}" "Staging API deploy" "${TAG}" || result=$?

case "${result}" in
  0)
    echo "Staging API deployed at ${TAG} ✅"
    echo "Staging API deployed at \`${TAG}\`." >> "$GITHUB_STEP_SUMMARY"
    ;;
  2)
    echo "::error::Check Coolify — staging is not on ${TAG}."
    exit 1
    ;;
  *)
    exit 1
    ;;
esac
