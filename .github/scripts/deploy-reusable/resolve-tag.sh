#!/usr/bin/env bash
# Decide which image tag to deploy, and whether it has to be built first.
#
# SSM_PREFIX, REQUESTED_TAG, ROLLBACK and ENVIRONMENT come from the calling
# step's env.
set -euo pipefail

current=$(aws ssm get-parameter --name "${SSM_PREFIX}/config/IMAGE_TAG" \
  --query Parameter.Value --output text)

if [ "${ROLLBACK}" = "true" ]; then
  tag=$(aws ssm get-parameter --name "${SSM_PREFIX}/config/PREVIOUS_IMAGE_TAG" \
    --query Parameter.Value --output text)
  build=false
  if [ "${tag}" = "${current}" ]; then
    echo "::error::PREVIOUS_IMAGE_TAG and IMAGE_TAG are both '${tag}' — there is no earlier deployment on record to roll back to. Pass an explicit tag instead."
    exit 1
  fi
elif [ -n "${REQUESTED_TAG}" ]; then
  tag="${REQUESTED_TAG}"
  build=false
else
  # Nothing requested: build what is checked out. The short SHA makes the
  # deployed tag traceable back to a commit.
  tag=$(git rev-parse --short HEAD)
  build=true
fi

{
  echo "tag=${tag}"
  echo "current=${current}"
  echo "build=${build}"
} >> "$GITHUB_OUTPUT"

echo "Deploying '${tag}' to ${ENVIRONMENT} (currently '${current}', build=${build})."
