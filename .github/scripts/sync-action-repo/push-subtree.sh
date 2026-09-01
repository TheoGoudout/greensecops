#!/usr/bin/env bash
# Split action/ out of this repository and push it to the public action repo.
#
# TOKEN and TARGET come from the calling step's env, so neither the token nor
# the repository name is interpolated into a shell command by the workflow.
set -euo pipefail

git remote add public-action "https://x-access-token:${TOKEN}@github.com/${TARGET}.git"
git fetch public-action main

# public main is one commit ahead after every run (the dist rebuild commit added
# by the next step), so the freshly split source commit is never a descendant of
# it. Merge that prior state in before pushing so the push stays a plain
# fast-forward instead of a non-ff rejection.
SPLIT_SHA=$(git subtree split --prefix=action)
git checkout -b sync-branch "${SPLIT_SHA}"
git merge public-action/main -m "chore: merge public main" --no-edit
git push public-action sync-branch:main
