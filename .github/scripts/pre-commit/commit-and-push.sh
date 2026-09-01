#!/usr/bin/env bash
# Commit whatever the hooks reformatted back onto the pull request's branch.
set -euo pipefail

git config user.name "github-actions[bot]"
git config user.email "github-actions[bot]@users.noreply.github.com"
git add -A
if git diff --staged --quiet; then
  echo "No changes to commit"
else
  git commit -m "🎨 Auto format and update with pre-commit"
  git push
fi
