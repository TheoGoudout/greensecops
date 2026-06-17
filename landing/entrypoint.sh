#!/bin/sh
set -e
APP_URL="${APP_URL:-https://app.greensecops.io}"
for f in /usr/share/nginx/html/*.html; do
  envsubst '${APP_URL}' < "$f" > "${f}.tmp" && mv "${f}.tmp" "$f"
done
exec "$@"
