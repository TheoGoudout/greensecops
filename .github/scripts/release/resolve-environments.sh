#!/usr/bin/env bash
# Decide which environments this release deploys to.
#
#                  STAGING_ENABLED=true        otherwise
#   pre-release -> staging                     nothing
#   release     -> staging and production      production
#
# Staging is opt-in through the STAGING_ENABLED repository variable, so a
# repository that runs production alone needs no staging Environment at all.
# When it is on, staging always takes the release, so it runs what production
# runs (or is about to). Dev is not listed: it deploys itself from main.
#
# PRERELEASE and STAGING_ENABLED come from the calling step's env.
set -euo pipefail

environments=()
if [ "${STAGING_ENABLED:-}" = "true" ]; then
  environments+=('"staging"')
fi
if [ "$PRERELEASE" != "true" ]; then
  environments+=('"production"')
fi

json="[$(IFS=,; echo "${environments[*]-}")]"
echo "environments=${json}" >> "$GITHUB_OUTPUT"
echo "Deploying to ${json}."
