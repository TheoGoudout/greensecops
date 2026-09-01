#!/usr/bin/env bash
# Say what was deployed, and how to undo it.
#
# TAG, PREVIOUS, BUILT, OUTCOME and ENVIRONMENT come from the calling step's env.
set -euo pipefail

{
  echo "## ${OUTCOME}: ${ENVIRONMENT}"
  echo
  echo "| | |"
  echo "|---|---|"
  echo "| Deployed tag | \`${TAG}\` |"
  echo "| Previous tag | \`${PREVIOUS}\` |"
  echo "| Images built | ${BUILT} |"
  echo
  if [ "${OUTCOME}" != "success" ]; then
    echo "The rollout did not complete. Run the **rollback** workflow"
    echo "against \`${ENVIRONMENT}\` to return to \`${PREVIOUS}\`."
  else
    echo "To undo this, run the **rollback** workflow against"
    echo "\`${ENVIRONMENT}\` — it will deploy \`${PREVIOUS}\`."
  fi
} >> "$GITHUB_STEP_SUMMARY"
