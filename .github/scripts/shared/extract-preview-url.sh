#!/usr/bin/env bash
# Publish the workers.dev preview URL a wrangler upload printed, as a step output.
#
#   extract-preview-url.sh <surface>
#
# <surface> names the site in the warning only — "landing", "the dashboard",
# "the documentation" — so a run that produced no URL says which one.
#
# STDOUT and STDERR come from the wrangler action's command-output and
# command-stderr outputs, via the calling step's env.
set -euo pipefail

if [ "$#" -ne 1 ]; then
  echo "usage: $0 <surface>" >&2
  exit 2
fi

surface=$1

# wrangler reports the version preview URL on one stream or the other depending
# on how it detects the terminal, so search both.
url=$(printf '%s\n%s\n' "${STDOUT}" "${STDERR}" \
  | grep -Eom1 'https://[a-z0-9.-]+\.workers\.dev' || true)
if [ -z "${url}" ]; then
  echo "::warning::No preview URL in the wrangler output for ${surface}."
fi
echo "url=${url}" >> "$GITHUB_OUTPUT"
