#!/usr/bin/env bash
# Cut this version's section out of release-notes.md into the draft's body file.
#
# VERSION comes from the calling step's env.
set -euo pipefail

python3 scripts/cut_release_notes.py "${VERSION}" --body-file "${RUNNER_TEMP}/release-body.md"
