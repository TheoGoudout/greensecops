#!/usr/bin/env bash
# Commit the version bump, tag it, and push both to main.
#
# TOKEN, VERSION and TAG come from the calling step's env. TOKEN is the PAT
# rather than the default GITHUB_TOKEN because a push made with the latter
# starts no workflow — images.yml would never build the release images.
set -euo pipefail

if [ -z "${TOKEN}" ]; then
  echo "::error::The LATEST_CHANGES secret is not set. It is the PAT that lets this workflow push to main and create the tag; without it images.yml would never build the release images."
  exit 1
fi

git config user.name "greensecops-bot"
git config user.email "bot@greensecops.com"

git add -A
git commit -m "chore: release ${TAG}"

# Assembled here rather than in a workflow expression, so the token never
# appears in one.
remote="https://x-access-token:${TOKEN}@github.com/${GITHUB_REPOSITORY}.git"

# The concurrency group makes a collision with latest-changes.yml unlikely
# rather than impossible — it only serialises this repo's own runs, and a human
# can always push. Rebase and retry rather than failing a release for a race
# that resolves itself.
for attempt in 1 2 3; do
  git pull --rebase "${remote}" main && break
  if [ "${attempt}" = "3" ]; then
    echo "::error::Could not rebase onto main after 3 attempts."
    exit 1
  fi
  sleep $((attempt * 5))
done

# The tag is created after the rebase so it points at the commit that actually
# lands on main, not at a pre-rebase one that no branch contains.
git tag -a "${TAG}" -m "Release ${TAG}"

git push "${remote}" HEAD:main
git push "${remote}" "refs/tags/${TAG}"
