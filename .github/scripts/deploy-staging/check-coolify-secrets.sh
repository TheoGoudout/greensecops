#!/usr/bin/env bash
# Decide whether the staging API deploy runs, and publish that as a step output.
#
# Skip in one direction only, exactly as the Cloudflare and Coolify checks
# elsewhere do. No secrets at all is a fork, or an account that runs no Coolify
# — nothing to deploy. *Some* of them is a misconfiguration, and going green
# having deployed nothing is how a staging deployment quietly stops tracking
# main.
#
# COOLIFY_URL, COOLIFY_TOKEN and UUID come from the calling step's env.
set -euo pipefail

present=0; missing=""
for name in COOLIFY_URL COOLIFY_TOKEN UUID; do
  if [ -n "${!name}" ]; then
    present=$((present + 1))
  else
    missing="${missing} ${name}"
  fi
done

if [ "${present}" -eq 0 ]; then
  echo "::notice::No Coolify secrets on this repository — skipping the staging API deploy."
  echo "run=false" >> "$GITHUB_OUTPUT"
  exit 0
fi

if [ -n "${missing}" ]; then
  echo "::error::Coolify is partly configured: missing${missing}. Set all three or none — a partial set would deploy nothing and still pass."
  exit 1
fi

echo "run=true" >> "$GITHUB_OUTPUT"
