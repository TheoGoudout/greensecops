#!/usr/bin/env bash
# Write the environment's resolved URLs into the run summary.
set -euo pipefail

{
  echo "## ${ENVIRONMENT}"
  echo
  echo "| Surface | URL |"
  echo "|---|---|"
  echo "| Landing | ${MARKETING_URL} |"
  echo "| Dashboard | ${APP_URL} |"
  echo "| API | ${API_URL} |"
  echo "| Documentation | ${DOCS_URL} |"
} >> "$GITHUB_STEP_SUMMARY"
