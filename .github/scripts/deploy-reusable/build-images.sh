#!/usr/bin/env bash
# Build and publish the images for the tag being deployed.
#
# GREENSECOPS_ENV, AWS_REGION and TAG come from the calling step's env.
set -euo pipefail

cd deploy/ansible
ansible-playbook -i localhost, playbooks/build.yml \
  -e image_tag="${TAG}"
