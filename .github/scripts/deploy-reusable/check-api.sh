#!/usr/bin/env bash
# Confirm the environment's API answers after the rollout.
#
# SSM_PREFIX comes from the calling step's env.
set -euo pipefail

backend=$(aws ssm get-parameter --name "${SSM_PREFIX}/config/BACKEND_HOST" \
  --query Parameter.Value --output text)
url="${backend}/api/v1/system/health"

# The load balancer needs a moment to see the replaced targets as healthy even
# after the containers report ready.
for attempt in $(seq 1 30); do
  if curl -fsS --max-time 10 "${url}" >/dev/null; then
    echo "${url} responded on attempt ${attempt}."
    exit 0
  fi
  sleep 10
done
echo "::error::${url} did not respond within 5 minutes of the rollout finishing."
exit 1
