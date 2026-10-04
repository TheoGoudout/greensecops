#!/usr/bin/env bash
# Point the production resource at the release tag and queue a deploy.
#
# Two settings, because they do different jobs and neither is enough alone.
# git_branch decides which tree Coolify reads compose.yml from (it takes a tag,
# confirmed against the live API); the TAG variable decides which image that
# compose file pulls, and the resource's own variable overrides the
# ${TAG:-latest} default no matter which tree is checked out. Both are partial
# updates — no other field of the resource is touched, and no branch is created
# anywhere.
#
# Unlike staging, the resource's git ref is repointed at all: production is
# pinned to the release rather than tracking `main`.
#
# COOLIFY_URL, COOLIFY_TOKEN, UUID and TAG come from the calling step's env.
set -euo pipefail

ROOT=$(cd -- "$(dirname -- "$0")/../../.." && pwd)
# shellcheck source=.github/scripts/lib/coolify.sh
. "${ROOT}/.github/scripts/lib/coolify.sh"

coolify_require_env COOLIFY_URL COOLIFY_TOKEN UUID

echo "Repointing ${UUID} at ${TAG}"
coolify_call PATCH "/applications/${UUID}" \
  -d "$(jq -nc --arg ref "${TAG}" '{git_branch: $ref}')"
coolify_require_ok "Repointing the resource at ${TAG}"

echo "Setting TAG=${TAG}"
coolify_upsert_env "${UUID}" TAG "${TAG}"

echo "Triggering the deploy"
deployment=$(coolify_trigger_deploy "${UUID}")
echo "deployment=${deployment}" >> "$GITHUB_OUTPUT"
echo "Deployment ${deployment} queued."
