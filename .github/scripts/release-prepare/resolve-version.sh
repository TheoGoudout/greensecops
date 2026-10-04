#!/usr/bin/env bash
# Resolve the version being released, refuse one that is taken or goes
# backwards, and publish it as step outputs.
#
# BUMP, EXPLICIT and GH_TOKEN come from the calling step's env, which is where
# the workflow's inputs are routed: an input interpolated into a script lands
# verbatim in the shell, which is the template-injection sink zizmor flags.
set -euo pipefail

if [ -n "${EXPLICIT}" ]; then
  version=$(python3 scripts/bump_version.py "${EXPLICIT}" --print-only)
else
  version=$(python3 scripts/bump_version.py --bump "${BUMP}" --print-only)
fi
tag="v${version}"

if git rev-parse -q --verify "refs/tags/${tag}" >/dev/null; then
  echo "::error::Tag ${tag} already exists. Pass an explicit version, or pick a different bump."
  exit 1
fi

# A draft also reserves the tag name, and has no tag behind it yet — so the
# check above cannot see one. A second draft for the same name would race the
# first to create the tag.
if gh release view "${tag}" --repo "${GITHUB_REPOSITORY}" >/dev/null 2>&1; then
  echo "::error::A release (possibly a draft) already exists for ${tag}. Publish or delete it first."
  exit 1
fi

# Guard against going backwards. Python's packaging order, not `sort -V`, which
# ranks 0.12.0-rc2 above 0.12.0 and would reject every rc promotion.
uv run --no-project --with "packaging>=24" python - "${version}" <<'PY'
import subprocess
import sys

from packaging.version import InvalidVersion, Version

try:
    candidate = Version(sys.argv[1])
except InvalidVersion:
    print(f"::warning::{sys.argv[1]} is not a PEP 440 version; not checking it sorts above the existing tags.")
    sys.exit(0)
tags = subprocess.run(["git", "tag", "--list", "v*"], capture_output=True, text=True, check=True)
existing = []
for name in tags.stdout.split():
    try:
        existing.append(Version(name[1:]))
    except InvalidVersion:
        continue
if existing and candidate <= max(existing):
    sys.exit(f"::error::{candidate} does not sort above the highest existing tag v{max(existing)}.")
PY

{
  echo "version=${version}"
  echo "tag=${tag}"
} >> "$GITHUB_OUTPUT"
echo "Releasing ${version}."
