#!/usr/bin/env bash
# Align FIRST_SUPERUSER_PASSWORD with SERVICE_PASSWORD_FIRSTSUPERUSER so
# Playwright tests can authenticate against the seeded superuser account.
set -euo pipefail

cp .env.example .env
cp frontend/.env.example frontend/.env
printf '\nFIRST_SUPERUSER_PASSWORD=%s\n' "$SERVICE_PASSWORD_FIRSTSUPERUSER" >> .env
