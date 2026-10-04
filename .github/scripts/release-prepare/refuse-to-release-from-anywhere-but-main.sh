#!/usr/bin/env bash
# Releases are cut from main, and the bump commit is pushed straight to it. A
# dispatch from another branch would bump, notes and all, a tree that is not
# what main holds.
#
# REF comes from the calling step's env.
set -euo pipefail

if [ "$REF" != "refs/heads/main" ]; then
  echo "::error::Releases must be cut from main, got ${REF}."
  exit 1
fi
