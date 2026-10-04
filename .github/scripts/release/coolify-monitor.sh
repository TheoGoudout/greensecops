#!/usr/bin/env bash
# Watch the production deploy through to its conclusion.
#
# COOLIFY_URL, COOLIFY_TOKEN, TAG and DEPLOYMENT come from the calling step's env.
set -euo pipefail

ROOT=$(cd -- "$(dirname -- "$0")/../../.." && pwd)
# shellcheck source=.github/scripts/lib/coolify.sh
. "${ROOT}/.github/scripts/lib/coolify.sh"

result=0
coolify_monitor_deploy "${DEPLOYMENT}" "Coolify deploy" "${TAG}" || result=$?

case "${result}" in
  0)
    echo "Deployed ${TAG} ✅"
    ;;
  2)
    echo "::error::Check Coolify — the dashboard has NOT been promoted."
    exit 1
    ;;
  *)
    exit 1
    ;;
esac
