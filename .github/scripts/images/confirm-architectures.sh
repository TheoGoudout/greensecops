#!/usr/bin/env bash
# Confirm the published manifest carries both architectures.
#
# IMAGE and VERSION come from the calling step's env.
set -euo pipefail

platforms=$(docker buildx imagetools inspect "${IMAGE}:${VERSION}" --raw \
  | jq -r '.manifests[] | select(.platform.os == "linux") | .platform.architecture' \
  | sort -u | tr '\n' ' ')
echo "Published ${IMAGE}:${VERSION} for: ${platforms}"
for arch in amd64 arm64; do
  case " ${platforms} " in
    *" ${arch} "*) ;;
    *) echo "::error::${IMAGE}:${VERSION} has no ${arch} manifest"; exit 1 ;;
  esac
done
