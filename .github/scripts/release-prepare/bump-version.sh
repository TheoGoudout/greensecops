#!/usr/bin/env bash
# Write the new version into every manifest, then check they all agree.
#
# VERSION comes from the calling step's env.
set -euo pipefail

python3 scripts/bump_version.py "${VERSION}"
python3 scripts/validate_versions.py
