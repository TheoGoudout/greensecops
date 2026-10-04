#!/usr/bin/env bash
# Open the release as a draft, for a human to review and publish.
#
# The tag does not exist yet. --target pins the commit GitHub will create it on
# when the draft is published, so later pushes to main cannot move it.
#
# GH_TOKEN, TAG, SHA and VERSION come from the calling step's env.
set -euo pipefail

# A hyphen in the version means a pre-release (0.11.0-rc1). Marking it as such
# is not cosmetic: sync-action-repo.yml branches on the release's `prerelease`
# flag and skips moving the floating major tag for one, which is what stops a
# candidate becoming what `@v0` resolves to.
args=(--draft --target "${SHA}" --title "${TAG}" --notes-file "${RUNNER_TEMP}/release-body.md")
case "${VERSION}" in
  *-*) args+=(--prerelease) ;;
esac

gh release create "${TAG}" "${args[@]}"
