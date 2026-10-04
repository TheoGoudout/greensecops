#!/usr/bin/env bash
# Summarise the release: the images, then each environment's deploy.
#
# Each environment's own deploy (deploy-environment.yml) writes its detailed
# summary — the API and the static surfaces, in that order. This is the
# overview.
#
# TAG, IMAGES, DEPLOY and ENVIRONMENTS come from the calling step's env.
set -euo pipefail

{
  echo "## Release ${TAG}"
  echo
  echo "| Stage | Result |"
  echo "|---|---|"
  echo "| Images | ${IMAGES} |"
  echo "| Deploy to ${ENVIRONMENTS:-nothing} (API, then static surfaces) | ${DEPLOY} |"
  echo
  if [ "${DEPLOY}" = "failure" ]; then
    echo "> At least one environment did not finish. Its own summary says which"
    echo "> half: an API on ${TAG} with the dashboard behind is the tolerable"
    echo "> direction — re-run the failed jobs, or re-drive one half with"
    echo "> \`targets\`."
  fi
} >> "$GITHUB_STEP_SUMMARY"
