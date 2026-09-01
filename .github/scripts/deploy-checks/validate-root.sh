#!/usr/bin/env bash
# Initialise and validate one Terraform root.
#
#   validate-root.sh <root-directory>
#
# -backend=false so no state bucket and no AWS credentials are needed; this
# checks the configuration, it does not touch an account. TF_IN_AUTOMATION is
# set by the calling step.
set -euo pipefail

if [ "$#" -ne 1 ]; then
  echo "usage: $0 <root-directory>" >&2
  exit 2
fi

root=$1

terraform -chdir="${root}" init -backend=false -input=false
terraform -chdir="${root}" validate
