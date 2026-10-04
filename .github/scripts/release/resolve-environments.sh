#!/usr/bin/env bash
# Decide which environments this release deploys to.
#
#   pre-release -> staging
#   release     -> staging and production, side by side
#
# Staging always takes the release, so it runs what production runs (or is
# about to). Dev is not listed: it deploys itself from main.
#
# PRERELEASE comes from the calling step's env.
set -euo pipefail

if [ "$PRERELEASE" = "true" ]; then
  environments='["staging"]'
else
  environments='["staging","production"]'
fi

echo "environments=${environments}" >> "$GITHUB_OUTPUT"
echo "Deploying to ${environments}."
