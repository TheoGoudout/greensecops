#!/usr/bin/env bash
# Install the Terraform binary onto a runner.
#
# Installed directly rather than via an action: one fewer third-party dependency
# to pin, matching how opa.yml installs the OPA binary. TERRAFORM_VERSION is
# pinned in the calling workflow's env.
set -euo pipefail

curl -fsSL -o /tmp/terraform.zip \
  "https://releases.hashicorp.com/terraform/${TERRAFORM_VERSION}/terraform_${TERRAFORM_VERSION}_linux_amd64.zip"
sudo unzip -o -q /tmp/terraform.zip -d /usr/local/bin
terraform version
