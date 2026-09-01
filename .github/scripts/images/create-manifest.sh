#!/usr/bin/env bash
# Assemble the per-architecture digests into one multi-architecture manifest.
#
#   create-manifest.sh <digest-dir>
#
# Every file in <digest-dir> is named for one architecture's digest; the tags
# come from the metadata action, which exports them as DOCKER_METADATA_OUTPUT_JSON.
# IMAGE comes from the calling step's env.
set -euo pipefail

if [ "$#" -ne 1 ]; then
  echo "usage: $0 <digest-dir>" >&2
  exit 2
fi

cd "$1"

# Both substitutions are deliberately unquoted: each expands to a list of
# separate arguments — `-t <tag>` pairs, and one `image@sha256:<digest>` per
# file — rather than to one argument containing spaces.
# shellcheck disable=SC2046,SC2086
docker buildx imagetools create \
  $(jq -cr '.tags | map("-t " + .) | join(" ")' <<< "$DOCKER_METADATA_OUTPUT_JSON") \
  $(printf "${IMAGE}@sha256:%s " *)
