#!/usr/bin/env bash
# Resolve the immutable per-commit tag, confirm it is in the registry, and
# publish it as a step output.
#
# This is the reason this deployment stopped serving stale images. `latest`
# moves under a name that does not change, so a host that already has it has no
# reason to look again — Compose's default pull policy is `missing`, and
# Coolify's ordinary deploy does not force a pull. `sha-<short>` is a reference
# the host has never seen, so the pull is structural rather than something a
# flag has to remember to ask for. It also makes "what is staging running?"
# exactly answerable.
#
# The same tag the merge job publishes through metadata-action's
# `type=sha,format=short`. Confirmed against the registry rather than assumed:
# if that format ever changes, this must fail loudly here instead of pinning the
# resource to a tag that does not exist.
#
# GH_TOKEN and OWNER come from the calling step's env; REGISTRY from the
# workflow's.
set -euo pipefail

tag="sha-${GITHUB_SHA:0:7}"
owner_lc=${OWNER,,}

echo "${GH_TOKEN}" | docker login "${REGISTRY}" -u "${GITHUB_ACTOR}" --password-stdin

for image in backend opa; do
  reference="${REGISTRY}/${owner_lc}/greensecops-${image}:${tag}"
  if ! docker buildx imagetools inspect "${reference}" >/dev/null 2>&1; then
    echo "::error::${reference} does not exist, so the staging resource must not be pointed at ${tag}. Check the merge job's tags."
    exit 1
  fi
  echo "${reference} ✅"
done

echo "tag=${tag}" >> "$GITHUB_OUTPUT"
