#!/usr/bin/env bash
# Block until the release's images are in the registry.
#
# A poll, not a check. images.yml starts when release.yml pushes the tag, and it
# is four build jobs plus two manifest merges — if the draft is published
# promptly, which is the normal case, that run is still going. A one-shot check
# would turn an ordinary timing window into a failed release.
#
# GH_TOKEN, TAG and OWNER come from the calling step's env; REGISTRY from the
# workflow's.
set -euo pipefail

echo "${GH_TOKEN}" | docker login "${REGISTRY}" -u "${GITHUB_ACTOR}" --password-stdin

owner_lc=$(echo "${OWNER}" | tr '[:upper:]' '[:lower:]')
missing=""

for image in backend opa; do
  reference="${REGISTRY}/${owner_lc}/greensecops-${image}:${TAG}"
  echo "Waiting for ${reference}"
  found=false
  for attempt in $(seq 1 30); do
    if docker buildx imagetools inspect "${reference}" >/dev/null 2>&1; then
      echo "  present after ${attempt} attempt(s)."
      found=true
      break
    fi
    sleep 60
  done
  if [ "${found}" != "true" ]; then
    missing="${missing} ${reference}"
  fi
done

if [ -n "${missing}" ]; then
  echo "::error::Not published within 30 minutes:${missing}. Check the images.yml run for ${TAG}; nothing has been deployed."
  exit 1
fi
