#!/usr/bin/env bash
# Decide which halves of the promotion this run drives.
#
# `all` on the release trigger, and on a dispatch that did not narrow it. The
# point of narrowing is the half-failed release: Coolify deployed, Cloudflare
# did not, and the fix is to re-drive the dashboard alone rather than restart a
# rollout that already succeeded.
#
# TARGETS comes from the calling step's env.
set -euo pipefail

for target in coolify cloudflare; do
  if [ "${TARGETS}" = "all" ] || [ "${TARGETS}" = "${target}" ]; then
    echo "${target}=true" >> "$GITHUB_OUTPUT"
  else
    echo "${target}=false" >> "$GITHUB_OUTPUT"
  fi
done

echo "Targets: ${TARGETS}."
