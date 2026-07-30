# Partial backend configuration for staging:
#   terraform init -backend-config=env/staging.backend.hcl
#
# Same bucket as production, different key — one bucket per account, one state
# object per environment.

bucket = "greensecops-tfstate-CHANGEME"
key    = "staging/terraform.tfstate"
region = "eu-west-1"

encrypt    = true
kms_key_id = "arn:aws:kms:eu-west-1:123456789012:key/CHANGEME"

use_lockfile = true
