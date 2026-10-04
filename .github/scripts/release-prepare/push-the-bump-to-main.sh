#!/usr/bin/env bash
# Commit the version bump and push it to main, and report the commit that
# landed.
#
# No tag is created here. The draft release opened next names the tag and the
# commit, and GitHub creates the tag when a person publishes that draft — so a
# tag without a release cannot exist. That push of the tag is also what starts
# images.yml building the release images (a user's push, not GITHUB_TOKEN's,
# so it does trigger workflows).
#
# TOKEN and TAG come from the calling step's env. TOKEN is the PAT rather than
# the default GITHUB_TOKEN because a push made with the latter starts no
# workflow, so the bump commit would land on main with no CI.
set -euo pipefail

if [ -z "${TOKEN}" ]; then
  echo "::error::The LATEST_CHANGES secret is not set. It is the PAT that lets this workflow push the bump to main; without it the released commit would get no CI."
  exit 1
fi

git config user.name "greensecops-bot"
git config user.email "bot@greensecops.com"

git add -A
git commit -m "chore: release ${TAG}"

# Assembled here rather than in a workflow expression, so the token never
# appears in one.
remote="https://x-access-token:${TOKEN}@github.com/${GITHUB_REPOSITORY}.git"

# A pull request merging mid-run moves main under this push. Rebase and retry
# rather than failing a release for a race that resolves itself.
for attempt in 1 2 3; do
  git pull --rebase "${remote}" main && git push "${remote}" HEAD:main && break
  if [ "${attempt}" = "3" ]; then
    echo "::error::Could not land the bump on main after 3 attempts."
    exit 1
  fi
  sleep $((attempt * 5))
done

# After the rebase, so the draft targets the commit that actually landed on
# main rather than a pre-rebase one no branch contains.
echo "sha=$(git rev-parse HEAD)" >> "$GITHUB_OUTPUT"
