#!/usr/bin/env bash
# Point the resource at the image tag and queue a deploy.
#
# Two settings, because they do different jobs. The TAG variable decides which
# image the compose file pulls, and the resource's own variable overrides the
# ${TAG:-latest} default no matter which tree is checked out. git_branch decides
# which tree Coolify reads compose.yml from (it takes a tag, confirmed against
# the live API): it is repointed only when REF is set — production is pinned to
# the release, while staging tracks `main` permanently. Both are partial
# updates; no other field of the resource is touched.
#
# COOLIFY_URL, COOLIFY_TOKEN, UUID, TAG and REF come from the calling step's env.
set -euo pipefail

ROOT=$(cd -- "$(dirname -- "$0")/../../.." && pwd)
# shellcheck source=.github/scripts/lib/coolify.sh
. "${ROOT}/.github/scripts/lib/coolify.sh"

coolify_require_env COOLIFY_URL COOLIFY_TOKEN UUID

if [ -n "${REF}" ]; then
  echo "Repointing ${UUID} at ${REF}"
  coolify_call PATCH "/applications/${UUID}" \
    -d "$(jq -nc --arg ref "${REF}" '{git_branch: $ref}')"
  coolify_require_ok "Repointing the resource at ${REF}"
fi

echo "Setting TAG=${TAG}"
coolify_upsert_env "${UUID}" TAG "${TAG}"

echo "Triggering the deploy"
deployment=$(coolify_trigger_deploy "${UUID}")
echo "deployment=${deployment}" >> "$GITHUB_OUTPUT"
echo "Deployment ${deployment} queued."
