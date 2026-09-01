#!/usr/bin/env bash
# Say what the release did, and what a human has to do next.
#
# TAG, OUTCOME and REPO_URL come from the calling step's env.
set -euo pipefail

{
  echo "## ${OUTCOME}: ${TAG}"
  echo
  if [ "${OUTCOME}" = "success" ]; then
    echo "The version is bumped, the notes are cut and **${TAG}** is tagged."
    echo "\`images.yml\` is now building \`greensecops-{backend,opa}:${TAG}\`."
    echo
    echo "Nothing is deployed yet. Review the draft at ${REPO_URL}/releases —"
    echo "**publishing it** runs \`release-deploy.yml\`, which promotes Coolify"
    echo "and then Cloudflare."
  else
    echo "The release did not complete. If the tag was pushed but the draft"
    echo "was not created, delete the tag before retrying:"
    echo
    echo '```'
    echo "git push origin :refs/tags/${TAG}"
    echo '```'
  fi
} >> "$GITHUB_STEP_SUMMARY"
