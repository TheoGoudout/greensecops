#!/usr/bin/env bash
# Say what the release did, and what a human has to do next.
#
# TAG, OUTCOME and REPO_URL come from the calling step's env.
set -euo pipefail

{
  echo "## ${OUTCOME}: ${TAG}"
  echo
  if [ "${OUTCOME}" = "success" ]; then
    echo "The version is bumped on main and the notes are cut into a **draft**"
    echo "release for ${TAG}."
    echo
    echo "**Nothing is tagged or deployed yet.** Review the draft at"
    echo "${REPO_URL}/releases — **publishing it** creates the tag, which starts"
    echo "\`images.yml\` building \`greensecops-{backend,opa}:${TAG}\`, and runs"
    echo "\`release-deploy.yml\`, which waits for those images, then promotes"
    echo "Coolify and then Cloudflare."
  else
    echo "The release did not complete, and no tag was created. If the log shows"
    echo "the bump commit landed on main but no draft was opened, open it by hand"
    echo "against that commit (publishing it will create the tag there):"
    echo
    echo '```'
    echo "gh release create ${TAG} --draft --target <bump commit SHA> --title ${TAG}"
    echo '```'
    echo
    echo "Otherwise nothing changed, and the workflow can simply be run again."
  fi
} >> "$GITHUB_STEP_SUMMARY"
