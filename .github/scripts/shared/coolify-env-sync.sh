#!/usr/bin/env bash
# Push an environment's public URLs onto its Coolify resource.
#
# Three of the backend's settings name hostnames that Coolify cannot generate.
# SERVICE_URL_* magic is per-service — the identifier is a compose service name
# and the value comes from that service's FQDN — and deploy/coolify/compose.yml
# has no frontend, landing or docs service, because those three are Cloudflare
# Workers. So FRONTEND_HOST, MARKETING_URL and DOCS_URL had to be typed into
# Coolify by hand, and a variable Coolify has never heard of is substituted as
# the empty string rather than refused. The backend's env_ignore_empty then took
# the localhost default for FRONTEND_HOST, which is the deployment's only CORS
# origin and the host of the GitHub OAuth callback: staging answered every
# request correctly and the browser discarded every answer.
#
# This makes the repository the source of truth instead. The values come from
# deploy/cloudflare/env/<environment>.env — the same file the static builds are
# derived from — so both halves of a deployment cannot disagree about what a
# hostname is, which is the whole of the bug above.
#
#   COOLIFY_URL=... COOLIFY_TOKEN=... coolify-env-sync.sh <environment> <uuid>
#
# Idempotent: it reads the resource's current values first and calls nothing for
# the ones already correct, so an ordinary run reports no changes at all.
#
# It does not deploy. Coolify applies an environment variable on the resource's
# next deploy, so a *changed* value reaches the containers then rather than
# immediately — see the note this prints when it changes something.
#
# Both callers therefore run it immediately *before* the deploy they trigger:
# .github/workflows/images.yml for staging, release-deploy.yml for production.
# Run anywhere else in a pipeline and a changed hostname lands one deploy late.
set -euo pipefail

if [ "$#" -ne 2 ]; then
  echo "usage: $0 <environment> <resource-uuid>" >&2
  exit 2
fi

ENVIRONMENT=$1
UUID=$2
ROOT=$(cd -- "$(dirname -- "$0")/../../.." && pwd)
ENV_FILE="${ROOT}/deploy/cloudflare/env/${ENVIRONMENT}.env"

# shellcheck source=.github/scripts/lib/coolify.sh
. "${ROOT}/.github/scripts/lib/coolify.sh"

coolify_require_env COOLIFY_URL COOLIFY_TOKEN

# An empty UUID would otherwise reach the API as /applications//envs and come
# back as an unhelpful 404 rather than as the missing secret it is.
if [ -z "${UUID}" ]; then
  echo "::error::No resource UUID was given for ${ENVIRONMENT}. Check the COOLIFY_*_UUID secret." >&2
  exit 1
fi

if [ ! -f "${ENV_FILE}" ]; then
  echo "::error::${ENV_FILE} does not exist. Every environment needs one." >&2
  exit 1
fi

set -a
# shellcheck source=/dev/null  # the path is an argument, not a literal
. "${ENV_FILE}"
set +a

# The same derivation as .github/workflows/pages-reusable.yml's config job and
# deploy/terraform/locals.tf:294, so a hostname means the same thing on every
# deployment path.
FRONTEND_HOST="https://${APP_SUBDOMAIN:-}.${DOMAIN:-}"
MARKETING_URL="https://${DOMAIN:-}"
DOCS_URL="https://${DOCS_SUBDOMAIN:-}.${DOMAIN:-}"

# A bare https:// means DOMAIN was empty; a leading dot means the subdomain
# label was; a trailing dot means the domain was and the label was not. Those
# are the three shapes a half-filled file makes, and pushing any of them to a
# live resource would be worse than pushing nothing.
validate() {
  case "$2" in
    "" | https:// | https://.* | https://*. | *CHANGEME*)
      echo "::error::$1 resolves to '$2' for ${ENVIRONMENT}. Fix ${ENV_FILE}." >&2
      return 1
      ;;
  esac
}

invalid=0
validate FRONTEND_HOST "${FRONTEND_HOST}" || invalid=1
validate MARKETING_URL "${MARKETING_URL}" || invalid=1
validate DOCS_URL "${DOCS_URL}" || invalid=1
if [ "${invalid}" -ne 0 ]; then
  exit 1
fi

# Current values, so the common case makes no write at all and the changes this
# does make can be reported honestly.
#
# Coolify masks some values in this response, and a masked value that compares
# unequal costs one redundant PATCH rather than correctness — the upsert below
# is idempotent, so treating an unreadable value as differing is safe.
echo "Reading the current variables on ${UUID}"
coolify_call GET "/applications/${UUID}/envs"
coolify_require_ok "Listing the resource's environment variables"

current=$(jq -c '
  (if type == "array" then . else (.data // .envs // []) end)
  | map({(.key // ""): (.value // "")})
  | add // {}
' <<<"${coolify_body}" 2>/dev/null || echo '{}')

changes=()

sync_one() {
  local key=$1 value=$2 previous
  if jq -e --arg k "${key}" 'has($k)' <<<"${current}" >/dev/null; then
    previous=$(jq -r --arg k "${key}" '.[$k]' <<<"${current}")
  else
    previous="(unset)"
  fi

  if [ "${previous}" = "${value}" ]; then
    echo "  ${key} already correct"
    return
  fi

  coolify_upsert_env "${UUID}" "${key}" "${value}"

  echo "  ${key}: ${previous} -> ${value}"
  changes+=("${key}|${previous}|${value}")
}

echo "Syncing ${ENVIRONMENT} URLs to ${UUID}"
sync_one FRONTEND_HOST "${FRONTEND_HOST}"
sync_one MARKETING_URL "${MARKETING_URL}"
sync_one DOCS_URL "${DOCS_URL}"

if [ "${#changes[@]}" -eq 0 ]; then
  echo "Nothing to change."
  if [ -n "${GITHUB_STEP_SUMMARY:-}" ]; then
    echo "Coolify (${ENVIRONMENT}): URLs already correct, nothing changed." >>"${GITHUB_STEP_SUMMARY}"
  fi
  exit 0
fi

# Loud on purpose. This script does not deploy, so anything it changed applies
# on the resource's *next* deploy. Both callers trigger one straight after, so
# in CI that is the deploy in this same run — but run by hand, this is the whole
# of the warning.
if [ -n "${GITHUB_STEP_SUMMARY:-}" ]; then
  {
    echo "## Coolify (${ENVIRONMENT}): ${#changes[@]} variable(s) changed"
    echo
    echo "| Variable | Was | Now |"
    echo "|---|---|---|"
    for change in "${changes[@]}"; do
      IFS='|' read -r key previous value <<<"${change}"
      echo "| \`${key}\` | \`${previous}\` | \`${value}\` |"
    done
    echo
    echo "> These apply on the resource's **next deploy**. In CI that is the"
    echo "> deploy this same run triggers next. Run by hand, redeploy from"
    echo "> Coolify to apply them."
  } >>"${GITHUB_STEP_SUMMARY}"
fi

echo "Changed ${#changes[@]} variable(s); they apply on the next deploy."
