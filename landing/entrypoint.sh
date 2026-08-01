#!/bin/sh
set -e
APP_URL="${APP_URL:-https://app.greensecops.com}"
DOCS_URL="${DOCS_URL:-https://docs.greensecops.com}"
MARKETING_URL="${MARKETING_URL:-https://greensecops.com}"
SUPPORT_EMAIL="${SUPPORT_EMAIL:-support@greensecops.com}"
SALES_EMAIL="${SALES_EMAIL:-sales@greensecops.com}"
LEGAL_EMAIL="${LEGAL_EMAIL:-legal@greensecops.com}"
PRIVACY_EMAIL="${PRIVACY_EMAIL:-privacy@greensecops.com}"
export APP_URL DOCS_URL MARKETING_URL SUPPORT_EMAIL SALES_EMAIL LEGAL_EMAIL PRIVACY_EMAIL
# The scratch file lives outside the docroot for two reasons: the container runs
# as uid 101 and cannot create files in the root-owned docroot, and a `.tmp`
# beside the page would be briefly servable while the rewrite is in flight.
# `cat >` truncates the original in place, so only the file needs to be writable.
tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT
find /usr/share/nginx/html -name "*.html" | while read -r f; do
  envsubst '${APP_URL} ${DOCS_URL} ${MARKETING_URL} ${SUPPORT_EMAIL} ${SALES_EMAIL} ${LEGAL_EMAIL} ${PRIVACY_EMAIL}' < "$f" > "$tmp" && cat "$tmp" > "$f"
done
exec "$@"
