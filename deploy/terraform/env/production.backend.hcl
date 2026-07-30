# Partial backend configuration for production:
#   terraform init -backend-config=env/production.backend.hcl
#
# The bucket and KMS key are created by deploy/terraform/bootstrap; take these
# values from its `state_bucket` and `state_kms_key_arn` outputs.

bucket = "greensecops-tfstate-CHANGEME"
key    = "production/terraform.tfstate"
region = "eu-west-1"

encrypt    = true
kms_key_id = "arn:aws:kms:eu-west-1:123456789012:key/CHANGEME"

# Native S3 locking (Terraform 1.10+): a lock file beside the state object,
# no DynamoDB table to provision or pay for.
use_lockfile = true
