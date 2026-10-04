#!/usr/bin/env bash
# Build one static surface for one environment, outside GitHub Actions.
#
#   deploy/cloudflare/build.sh <landing|frontend|docs> <environment>
#
# This is the build command Cloudflare Workers Builds runs for dev, which
# deploys itself from main (deployment.md). Staging and production are built by
# pages-reusable.yml; this does the same steps, from the same scripts and the
# same deploy/cloudflare/env/<environment>.env, so the three environments are
# built alike:
#
#   landing   .github/scripts/pages-reusable/build-landing.sh -> landing/dist
#   frontend  bun run build with the VITE_* values                -> frontend/dist
#   docs      .github/scripts/pages-reusable/build-docs.sh     -> docs/_build/html
#
# then the surface's _headers, and — outside production — noindex.
#
# Run from the repository root. The deploy command that follows it is
# `cd <surface dir> && npx wrangler deploy --env <environment>`.
set -euo pipefail

if [ "$#" -ne 2 ]; then
  echo "usage: $0 <landing|frontend|docs> <environment>" >&2
  exit 2
fi
surface=$1
ENVIRONMENT=$2
export ENVIRONMENT

file="deploy/cloudflare/env/${ENVIRONMENT}.env"
if [ ! -f "${file}" ]; then
  echo "error: ${file} does not exist." >&2
  exit 1
fi
set -a
# shellcheck source=/dev/null
. "./${file}"
set +a

APP_URL="https://${APP_SUBDOMAIN:-}.${DOMAIN:-}"
API_URL="https://${API_SUBDOMAIN:-}.${DOMAIN:-}"
DOCS_URL="https://${DOCS_SUBDOMAIN:-}.${DOMAIN:-}"
MARKETING_URL="https://${DOMAIN:-}"
export APP_URL API_URL DOCS_URL MARKETING_URL

# Refuse an empty, half-formed or CHANGEME value, as resolve-urls.sh does for
# Actions: nothing downstream would notice one, and a dashboard built with an
# empty API URL answers every call with its own index.html.
require() {
  local failed=0 name value
  for name in "$@"; do
    value=${!name:-}
    case "${value}" in
      "" | https:// | https://.* | https://*. | *CHANGEME*)
        echo "error: ${name} is unset, incomplete or still CHANGEME for ${ENVIRONMENT}. Set it in ${file}." >&2
        failed=1
        ;;
    esac
  done
  return "${failed}"
}

# build-landing.sh needs envsubst, which a Workers Builds image may not have.
# This stands in for it with the same contract: substitute only the ${NAME}s
# listed in the first argument, from the environment.
if ! command -v envsubst >/dev/null 2>&1; then
  envsubst() {
    python3 -c '
import os, re, sys
names = set(re.findall(r"\$\{(\w+)\}", sys.argv[1]))
text = sys.stdin.read()
sys.stdout.write(re.sub(r"\$\{(\w+)\}", lambda m: os.environ.get(m.group(1), "") if m.group(1) in names else m.group(0), text))
' "$1"
  }
  export -f envsubst
fi

noindex() {
  if [ "${ENVIRONMENT}" != "production" ]; then
    .github/scripts/shared/noindex.sh "$1"
  fi
}

case "${surface}" in
  landing)
    require APP_URL DOCS_URL MARKETING_URL SUPPORT_EMAIL SALES_EMAIL LEGAL_EMAIL PRIVACY_EMAIL
    .github/scripts/pages-reusable/build-landing.sh
    noindex landing/dist
    ;;
  frontend)
    require API_URL GITHUB_CLIENT_ID GITHUB_APP_NAME
    export VITE_API_URL="${API_URL}"
    export VITE_GREENSECOPS_PUBLIC_URL="${API_URL}"
    export VITE_GITHUB_OAUTH_CLIENT_ID="${GITHUB_CLIENT_ID}"
    export VITE_GITHUB_APP_NAME="${GITHUB_APP_NAME}"
    export VITE_APP_ENVIRONMENT="${ENVIRONMENT}"
    # Workers Builds names the commit it builds; production shows no commit.
    if [ "${ENVIRONMENT}" != "production" ]; then
      export VITE_APP_COMMIT="${WORKERS_CI_COMMIT_SHA:-$(git rev-parse HEAD 2>/dev/null || true)}"
    fi
    bun ci
    (cd frontend && bun run build)
    cp deploy/cloudflare/frontend/_headers frontend/dist/_headers
    noindex frontend/dist
    ;;
  docs)
    require DOCS_URL
    if ! command -v uv >/dev/null 2>&1; then
      python3 -m pip install --quiet --user uv
      PATH="${HOME}/.local/bin:${PATH}"
    fi
    DOCS_BASE_URL="${DOCS_URL}" .github/scripts/pages-reusable/build-docs.sh
    cp deploy/cloudflare/docs/_headers docs/_build/html/_headers
    noindex docs/_build/html
    ;;
  *)
    echo "error: unknown surface '${surface}' (landing, frontend or docs)." >&2
    exit 2
    ;;
esac

echo "Built ${surface} for ${ENVIRONMENT}."
