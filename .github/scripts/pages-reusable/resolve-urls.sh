#!/usr/bin/env bash
# Resolve one environment's public URLs and contact addresses, as job outputs.
#
# ENVIRONMENT comes from the calling workflow's input.
set -euo pipefail

file="deploy/cloudflare/env/${ENVIRONMENT}.env"
if [ ! -f "${file}" ]; then
  echo "::error::${file} does not exist. Every environment pages.yml can dispatch needs one."
  exit 1
fi
set -a
# shellcheck source=/dev/null  # the path is an input, not a literal
. "./${file}"
set +a

missing=0

# Check one resolved value and publish it as a job output.
#
# Nothing downstream would fail on an empty one: GitHub renders an unset variable
# as the empty string, envsubst substitutes it happily, and a dashboard built
# with VITE_API_URL="" resolves every API call against its own Worker — which
# answers 200 with index.html because of not_found_handling, so the client
# parses HTML as JSON at runtime. A green build publishing a site broken only at
# runtime is the thing to prevent, so the check happens here or nowhere.
emit() {
  # A bare https:// means DOMAIN was empty; a leading dot means the subdomain
  # label was; a trailing dot means the domain was and the label was not. Those
  # are the three shapes a half-filled file makes.
  case "$2" in
    ""|https://|https://.*|https://*.|*CHANGEME*)
      echo "::error::$1 is unset, incomplete or still CHANGEME for ${ENVIRONMENT}. Set it in ${file}."
      missing=1
      ;;
  esac
  echo "$1=$2" >> "$GITHUB_OUTPUT"
}

# The same derivation as deploy/terraform/locals.tf:294, so a hostname means the
# same thing on both deployment paths.
emit app-url "https://${APP_SUBDOMAIN:-}.${DOMAIN:-}"
emit api-url "https://${API_SUBDOMAIN:-}.${DOMAIN:-}"
emit docs-url "https://${DOCS_SUBDOMAIN:-}.${DOMAIN:-}"
emit marketing-url "https://${DOMAIN:-}"

emit github-app-name "${GITHUB_APP_NAME:-}"
emit github-client-id "${GITHUB_CLIENT_ID:-}"
emit support-email "${SUPPORT_EMAIL:-}"
emit sales-email "${SALES_EMAIL:-}"
emit legal-email "${LEGAL_EMAIL:-}"
emit privacy-email "${PRIVACY_EMAIL:-}"

exit "${missing}"
