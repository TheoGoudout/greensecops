#!/usr/bin/env bash
# Resolve the tag this run promotes, and prove it names a published release.
#
# On the `release: published` trigger the tag comes from the event payload and
# is true by construction. On workflow_dispatch it is a string a human typed,
# and a typo would otherwise surface thirty minutes later as "not published
# within 30 minutes" from wait-for-images.sh — a timeout that reads like a
# broken build rather than a misspelled tag. Failing here costs five seconds
# and says what actually went wrong.
#
# GH_TOKEN and TAG come from the calling step's env.
set -euo pipefail

if [ -z "${TAG}" ]; then
  echo "::error::No tag to promote. The release payload was empty and no tag input was given."
  exit 1
fi

if ! is_draft=$(gh release view "${TAG}" --repo "${GITHUB_REPOSITORY}" --json isDraft --jq .isDraft); then
  echo "::error::No release named ${TAG}. Check the tag; nothing has been deployed."
  exit 1
fi

# A draft has no tag behind it yet, so every job downstream would be operating
# on a ref that does not exist.
if [ "${is_draft}" = "true" ]; then
  echo "::error::${TAG} is still a draft. Publish it — that is what creates the tag."
  exit 1
fi

echo "tag=${TAG}" >> "$GITHUB_OUTPUT"
echo "Promoting ${TAG}."
