#!/usr/bin/env bash
# Open the release as a draft, for a human to review and publish.
#
# GH_TOKEN, TAG and VERSION come from the calling step's env.
set -euo pipefail

# A hyphen in the version means a pre-release (0.11.0-rc1). Marking it as such
# is not cosmetic: sync-action-repo.yml branches on the release's `prerelease`
# flag and skips moving the floating major tag for one, which is what stops a
# candidate becoming what `@v0` resolves to.
prerelease=""
case "${VERSION}" in
  *-*) prerelease="--prerelease" ;;
esac

# Unquoted on purpose: an empty prerelease must expand to no argument at all,
# not to an empty one.
# shellcheck disable=SC2086
gh release create "${TAG}" \
  --draft \
  --title "${TAG}" \
  --notes-file "${RUNNER_TEMP}/release-body.md" \
  ${prerelease}
