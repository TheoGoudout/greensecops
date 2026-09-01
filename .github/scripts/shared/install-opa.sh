#!/usr/bin/env bash
# Install the OPA binary onto a runner.
#
# Installed directly rather than via an action: one fewer third-party dependency
# to pin, matching how deploy-checks.yml installs Terraform.
#
# OPA_VERSION comes from the calling workflow's env and is pinned there to match
# opa/Dockerfile, so local, server and CI evaluation all agree on a version.
set -euo pipefail

curl -fsSL -o /usr/local/bin/opa \
  "https://github.com/open-policy-agent/opa/releases/download/v${OPA_VERSION}/opa_linux_amd64_static"
chmod +x /usr/local/bin/opa
opa version
