#!/usr/bin/env bash
# Write this version's notes from the pull requests merged since the last
# stable release: into release-notes.md, and into the draft's body file.
#
# VERSION and GH_TOKEN come from the calling step's env; GITHUB_REPOSITORY is
# the runner's.
set -euo pipefail

python3 scripts/release_notes.py "${VERSION}" --body-file "${RUNNER_TEMP}/release-body.md"
echo "--- generated notes ---"
cat "${RUNNER_TEMP}/release-body.md"
