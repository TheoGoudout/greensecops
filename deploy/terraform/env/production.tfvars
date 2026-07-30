# Production. Every value below is an example — the bucket names must be
# globally unique and the domain and zone must be yours.
#
#   terraform init -backend-config=env/production.backend.hcl
#   terraform apply -var-file=env/production.tfvars

environment = "production"
aws_region  = "eu-west-1"

# Network. One NAT gateway per AZ: a single gateway would make one AZ's
# outage take out egress for the whole environment.
vpc_cidr                = "10.30.0.0/16"
availability_zone_count = 3
single_nat_gateway      = false

# DNS. The hosted zone must already exist and be delegated.
domain_name     = "greensecops.example.com"
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

# Two instances for anything on the request path, so a rolling instance
# refresh never drops to zero capacity.
services = {
  backend       = { instance_type = "t4g.medium", min = 2, max = 4, desired = 2 }
  frontend      = { instance_type = "t4g.small", min = 2, max = 2, desired = 2 }
  landing       = { instance_type = "t4g.small", min = 2, max = 2, desired = 2 }
  docs          = { instance_type = "t4g.small", min = 2, max = 2, desired = 2 }
  celery-worker = { instance_type = "t4g.medium", min = 2, max = 10, desired = 2 }
  celery-beat   = { instance_type = "t4g.small", min = 1, max = 1, desired = 1 }
  opa           = { instance_type = "t4g.small", min = 2, max = 6, desired = 2 }
}

# Data tier.
postgres_instance_class        = "db.m7g.large"
postgres_allocated_storage     = 100
postgres_multi_az              = true
postgres_backup_retention_days = 30
postgres_deletion_protection   = true

redis_node_type     = "cache.t4g.small"
redis_replica_count = 1

artifact_bucket_name          = "greensecops-artifacts-production-CHANGEME"
artifact_bucket_force_destroy = false
access_log_bucket_name        = "greensecops-alb-logs-production-CHANGEME"
ansible_transfer_bucket_name  = "greensecops-ansible-production-CHANGEME"

# Operations.
log_retention_days  = 90
deletion_protection = true
alarm_email         = "platform@example.com"

tags = {
  Owner      = "platform"
  CostCenter = "engineering"
}
