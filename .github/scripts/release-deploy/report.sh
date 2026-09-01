#!/usr/bin/env bash
# Summarise the release's three stages.
#
# TAG, IMAGES, API and STATIC come from the calling step's env.
set -euo pipefail

{
  echo "## Release ${TAG}"
  echo
  echo "| Stage | Result |"
  echo "|---|---|"
  echo "| Images | ${IMAGES} |"
  echo "| API (Coolify) | ${API} |"
  echo "| Static surfaces (Cloudflare) | ${STATIC} |"
  echo
  if [ "${API}" = "success" ] && [ "${STATIC}" != "success" ]; then
    echo "> The API is on ${TAG} but the dashboard is not. That is the"
    echo "> tolerable direction, but it is not the intended end state —"
    echo "> re-run the failed job, or roll the API back in Coolify."
  fi
} >> "$GITHUB_STEP_SUMMARY"
