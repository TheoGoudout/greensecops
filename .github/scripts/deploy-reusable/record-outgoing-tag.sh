#!/usr/bin/env bash
# Record the tag currently deployed, so the rollback workflow has a target.
#
# SSM_PREFIX and PREVIOUS come from the calling step's env.
set -euo pipefail

aws ssm put-parameter --name "${SSM_PREFIX}/config/PREVIOUS_IMAGE_TAG" \
  --value "${PREVIOUS}" --type String --overwrite
