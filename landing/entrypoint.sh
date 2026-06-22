#!/bin/sh
set -e
APP_URL="${APP_URL:-https://app.greensecops.io}"
DOCS_URL="${DOCS_URL:-https://docs.greensecops.io}"
find /usr/share/nginx/html -name "*.html" | while read -r f; do
  envsubst '${APP_URL} ${DOCS_URL}' < "$f" > "${f}.tmp" && mv "${f}.tmp" "$f"
done
exec "$@"
