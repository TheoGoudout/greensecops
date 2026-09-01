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

# The merge happens in a throwaway worktree, and not by checking the split
# commit out here. This checkout *is* the repository, and every later step in
# the job runs a script from .github/scripts/ inside it — a `git checkout` onto
# a tree that holds only the contents of action/ takes those scripts off disk,
# and the next step dies with "No such file or directory" rather than anything
# that names the real cause. A worktree leaves this checkout untouched.
WORKTREE=/tmp/action-subtree
rm -rf "${WORKTREE}"
git worktree prune
git worktree add --detach "${WORKTREE}" "${SPLIT_SHA}"
git -C "${WORKTREE}" merge public-action/main -m "chore: merge public main" --no-edit
git -C "${WORKTREE}" push public-action HEAD:main
git worktree remove --force "${WORKTREE}"
