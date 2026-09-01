#!/usr/bin/env bash
# Build landing/dist by substituting the site's URLs and contact addresses.
#
# landing/entrypoint.sh does this at container start-up. There is no container
# here, so the same substitution happens at build time from the same variable
# list — keep the two in step. entrypoint.sh's hardcoded defaults are the
# production values, which is why scripts/validate_landing_defaults.py asserts
# they still match deploy/cloudflare/env/production.env.
#
# The values come from the calling step's env.
set -euo pipefail

mkdir -p landing/dist
cp -r landing/assets landing/dist/
for f in landing/*.html; do
  out="landing/dist/$(basename "$f")"
  # shellcheck disable=SC2016  # envsubst takes the names literally: the single
  # quotes are what stop the shell expanding them, and what limits substitution
  # to this list rather than every $VAR in the page.
  envsubst '${APP_URL} ${DOCS_URL} ${MARKETING_URL} ${SUPPORT_EMAIL} ${SALES_EMAIL} ${LEGAL_EMAIL} ${PRIVACY_EMAIL}' \
    < "$f" > "$out"
done
# Reproduces `error_page 404 /index.html` from landing/nginx.conf.
# landing/wrangler.jsonc sets not_found_handling to "404-page", which serves this
# file — with a real 404 status — for anything unmatched. The extensionless paths
# the site links to need no rule: Workers' default html_handling resolves
# /pricing to pricing.html, which is the rest of nginx's `try_files $uri $uri.html`.
cp landing/dist/index.html landing/dist/404.html
cp deploy/cloudflare/landing/_headers landing/dist/_headers
