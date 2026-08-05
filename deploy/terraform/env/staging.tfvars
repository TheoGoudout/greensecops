# Staging, on the single_host topology: every container on one box, exactly
# like compose.yml, with PostgreSQL and Redis running alongside the
# application on a persistent volume.
#
#   terraform init -backend-config=env/staging.backend.hcl
#   terraform apply -var-file=env/staging.tfvars
#
# Staging stays on single_host permanently: it exists to exercise a deploy, not
# to survive an outage. Note that it therefore does *not* exercise RDS,
# ElastiCache or the internal load balancer — see the migration section of
# deploy/README.md for what to verify before moving production up a tier.

environment = "staging"
aws_region  = "eu-west-1"
topology    = "single_host"

# Two AZs because the load balancer requires subnets in at least two, even
# though only the first one holds an instance.
vpc_cidr                = "10.31.0.0/16"
availability_zone_count = 2

# DNS. The hosted zone must already exist and be delegated.
domain_name     = "staging.greensecops.example.com"
route53_zone_id = "Z0123456789ABCDEFGHIJ"

# Images, from the bootstrap root's outputs.
ecr_registry = "123456789012.dkr.ecr.eu-west-1.amazonaws.com"
ecr_repository_arns = [
  "arn:aws:ecr:eu-west-1:123456789012:repository/greensecops/backend",
  "arn:aws:ecr:eu-west-1:123456789012:repository/greensecops/frontend",
  "arn:aws:ecr:eu-west-1:123456789012:repository/greensecops/landing",
  "arn:aws:ecr:eu-west-1:123456789012:repository/greensecops/docs",
  "arn:aws:ecr:eu-west-1:123456789012:repository/greensecops/opa",
]
image_tag = "latest"

# GitHub Actions deploy identity, from the bootstrap root's
# github_oidc_provider_arn output. Leave empty to skip creating the role.
github_repository        = "TheoGoudout/greensecops"
github_oidc_provider_arn = "arn:aws:iam::123456789012:oidc-provider/token.actions.githubusercontent.com"

# One group running all seven containers plus PostgreSQL and Redis.
# t4g.medium (2 vCPU / 8 GiB) is the smallest size that comfortably holds the
# lot; t4g.xlarge if the Celery workers are busy.
groups = {
  app = { instance_type = "t4g.medium", min = 1, max = 1, desired = 1 }
}

celery_concurrency = 2

# The persistent volume is the only copy of the database in this topology.
state_volume_size               = 30
state_volume_snapshot_retention = 3

access_log_bucket_name        = "greensecops-alb-logs-staging-CHANGEME"
ansible_transfer_bucket_name  = "greensecops-ansible-staging-CHANGEME"

# Operations.
log_retention_days  = 14
deletion_protection = false
alarm_email         = ""

tags = {
  Owner = "platform"
}
