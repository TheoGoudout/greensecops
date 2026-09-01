#!/usr/bin/env bash
# Resolve the version being released, and publish it as step outputs.
#
# BUMP and EXPLICIT come from the calling step's env, which is where the
# workflow's inputs are routed: an input interpolated into a script lands
# verbatim in the shell, which is the template-injection sink zizmor flags.
set -euo pipefail

if [ -n "${EXPLICIT}" ]; then
  version=$(python3 scripts/bump_version.py "${EXPLICIT}" --print-only)
else
  version=$(python3 scripts/bump_version.py --bump "${BUMP}" --print-only)
fi

if git rev-parse -q --verify "refs/tags/v${version}" >/dev/null; then
  echo "::error::Tag v${version} already exists. Pass an explicit version, or pick a different bump."
  exit 1
fi

{
  echo "version=${version}"
  echo "tag=v${version}"
} >> "$GITHUB_OUTPUT"
echo "Releasing ${version}."
