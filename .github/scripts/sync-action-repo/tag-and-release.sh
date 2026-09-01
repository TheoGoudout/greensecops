#!/usr/bin/env bash
# Move the release and floating major tags on the public repo, and publish a
# release there.
#
# GH_TOKEN, TARGET, TAG, PRERELEASE, REPO and SHA come from the calling step's env.
set -euo pipefail

cd /tmp/public-action
major="v$(echo "${TAG}" | sed -E 's/^v?([0-9]+).*/\1/')"
git tag -f "${TAG}"
git tag -f "${major}"
git push origin "refs/tags/${TAG}" --force
git push origin "refs/tags/${major}" --force
prerelease_flag=""
if [ "${PRERELEASE}" = "true" ]; then
  prerelease_flag="--prerelease"
fi
# Unquoted on purpose: an empty flag must expand to no argument at all, not to
# an empty one.
# shellcheck disable=SC2086
gh release create "${TAG}" \
  --repo "${TARGET}" \
  --title "${TAG}" \
  --notes "Synced from ${REPO}@${SHA}" \
  ${prerelease_flag}
