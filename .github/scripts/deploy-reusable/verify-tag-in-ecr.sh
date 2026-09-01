#!/usr/bin/env bash
# Check every image exists in ECR at the tag about to be deployed.
#
# A cheap guard that turns a typo in a rollback tag into an error here rather
# than a pull failure part-way through rolling the instances.
#
# TAG comes from the calling step's env.
set -euo pipefail

missing=0
for image in backend frontend landing docs opa; do
  if ! aws ecr describe-images --repository-name "greensecops/${image}" \
       --image-ids "imageTag=${TAG}" >/dev/null 2>&1; then
    echo "::error::greensecops/${image}:${TAG} is not in ECR."
    missing=1
  fi
done
exit "${missing}"
