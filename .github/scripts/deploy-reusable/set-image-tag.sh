#!/usr/bin/env bash
# Point the environment at the tag being deployed.
#
# Idempotent: playbooks/build.yml already set this when it ran. Required when
# deploying an existing tag, where nothing was built.
#
# SSM_PREFIX and TAG come from the calling step's env.
set -euo pipefail

aws ssm put-parameter --name "${SSM_PREFIX}/config/IMAGE_TAG" \
  --value "${TAG}" --type String --overwrite
