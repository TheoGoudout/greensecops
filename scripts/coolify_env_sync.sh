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
#   COOLIFY_URL=... COOLIFY_TOKEN=... coolify_env_sync.sh <environment> <uuid>
#
# Idempotent: it reads the resource's current values first and calls nothing for
# the ones already correct, so an ordinary run reports no changes at all.
#
# It does not deploy. Coolify applies an environment variable on the resource's
# next deploy, so a *changed* value reaches the containers then rather than
# immediately — see the note this prints when it changes something.
set -euo pipefail

if [ "$#" -ne 2 ]; then
  echo "usage: $0 <environment> <resource-uuid>" >&2
  exit 2
fi

ENVIRONMENT=$1
UUID=$2
ROOT=$(cd -- "$(dirname -- "$0")/.." && pwd)
ENV_FILE="${ROOT}/deploy/cloudflare/env/${ENVIRONMENT}.env"

for name in COOLIFY_URL COOLIFY_TOKEN; do
  if [ -z "${!name:-}" ]; then
    echo "::error::The ${name} secret is not set." >&2
    exit 1
  fi
done

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

status=""
body=""

# Sets `status` and `body`. Call it directly — never inside $( ), which would
# run it in a subshell and discard both assignments.
#
# Not `curl -f`: that throws away the response body on an error status, which is
# the half of a 4xx that says *why*. Losing it turned the first real release
# failure into a bare "curl: (22) 404" with nothing to act on.
call() {
  local method=$1 path=$2
  shift 2
  local response
  response=$(curl -sS --max-time 60 -w '\n%{http_code}' -X "${method}" \
    -H "Authorization: Bearer ${COOLIFY_TOKEN}" \
    -H "Content-Type: application/json" \
    "${COOLIFY_URL}/api/v1${path}" "$@")
  status=${response##*$'\n'}
  body=${response%$'\n'*}
}

require_ok() {
  if [ "${status}" -lt 200 ] || [ "${status}" -ge 300 ]; then
    echo "::error::$1 failed with HTTP ${status}: ${body}" >&2
    exit 1
  fi
}

# Current values, so the common case makes no write at all and the changes this
# does make can be reported honestly.
#
# Coolify masks some values in this response, and a masked value that compares
# unequal costs one redundant PATCH rather than correctness — the upsert below
# is idempotent, so treating an unreadable value as differing is safe.
echo "Reading the current variables on ${UUID}"
call GET "/applications/${UUID}/envs"
require_ok "Listing the resource's environment variables"

current=$(jq -c '
  (if type == "array" then . else (.data // .envs // []) end)
  | map({(.key // ""): (.value // "")})
  | add // {}
' <<<"${body}" 2>/dev/null || echo '{}')

changes=()

sync_one() {
  local key=$1 value=$2 previous payload
  if jq -e --arg k "${key}" 'has($k)' <<<"${current}" >/dev/null; then
    previous=$(jq -r --arg k "${key}" '.[$k]' <<<"${current}")
  else
    previous="(unset)"
  fi

  if [ "${previous}" = "${value}" ]; then
    echo "  ${key} already correct"
    return
  fi

  payload=$(jq -nc --arg k "${key}" --arg v "${value}" '{key: $k, value: $v}')

  # Upsert, because PATCH and POST are not interchangeable here: PATCH updates
  # an existing variable and 404s when there is none; POST creates one. Which
  # applies depends on whether the variable was ever set on this resource by
  # hand — not something a deploy should have an opinion about.
  call PATCH "/applications/${UUID}/envs" -d "${payload}"
  if [ "${status}" = "404" ]; then
    echo "  No ${key} on this resource yet — creating it."
    call POST "/applications/${UUID}/envs" -d "${payload}"
    require_ok "Creating ${key}"
  else
    require_ok "Setting ${key}"
  fi

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
# on the resource's *next* deploy — and on staging, the deploy Coolify started
# from this very push is already running with the previous values.
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
    echo "> These apply on the resource's **next deploy**. Any deploy running"
    echo "> now started before the change and is using the previous values."
    echo "> Redeploy from Coolify to apply them immediately."
  } >>"${GITHUB_STEP_SUMMARY}"
fi

echo "Changed ${#changes[@]} variable(s); they apply on the next deploy."
