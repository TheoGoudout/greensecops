#!/usr/bin/env bash
# Say what the rollback reached, and fail the run if either half did not.
#
# The half-rolled-back state is the one worth being loud about: if Cloudflare
# went back and Coolify did not, production is serving an old dashboard against
# a new API, which is the mismatch direction the ordering exists to avoid.
#
# ENVIRONMENT, TAG, CLOUDFLARE_RESULT and COOLIFY_RESULT come from the calling
# step's env.
set -euo pipefail

{
  echo "## Rollback — ${ENVIRONMENT} to ${TAG}"
  echo
  echo "| Surface | Result |"
  echo "| --- | --- |"
  echo "| Cloudflare (landing, dashboard, docs) | ${CLOUDFLARE_RESULT} |"
  echo "| Coolify (API) | ${COOLIFY_RESULT} |"
  echo
  if [ "$CLOUDFLARE_RESULT" = "success" ] && [ "$COOLIFY_RESULT" != "success" ]; then
    echo "> The dashboard is back on ${TAG} but the API is not, so the client is"
    echo "> now older than the contract it is calling. Re-run the Coolify job, or"
    echo "> roll the dashboard forward again."
  fi
} >> "$GITHUB_STEP_SUMMARY"

failed=""
for half in "Cloudflare:${CLOUDFLARE_RESULT}" "Coolify:${COOLIFY_RESULT}"; do
  case "${half#*:}" in
    failure | cancelled) failed="${failed} ${half%%:*}(${half#*:})" ;;
  esac
done

if [ -n "$failed" ]; then
  echo "::error::Rollback did not complete:${failed}."
  exit 1
fi
