# Staging. Same topology as production so a deploy exercises the real shape,
# sized down and with the durability guarantees relaxed where they only cost
# money.
#
#   terraform init -backend-config=env/staging.backend.hcl
#   terraform apply -var-file=env/staging.tfvars

environment = "staging"
aws_region  = "eu-west-1"

# Two AZs and one NAT gateway: staging can tolerate an AZ outage taking egress
# with it, and the saving is roughly a NAT gateway per AZ per month.
vpc_cidr                = "10.31.0.0/16"
availability_zone_count = 2
single_nat_gateway      = true

domain_name     = "staging.greensecops.example.com"
route53_zone_id = "Z0123456789ABCDEFGHIJ"

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

# One of everything; the groups still exist, so scaling behaviour can be
# tested by raising max.
services = {
  backend       = { instance_type = "t4g.small", min = 1, max = 2, desired = 1 }
  frontend      = { instance_type = "t4g.micro", min = 1, max = 1, desired = 1 }
  landing       = { instance_type = "t4g.micro", min = 1, max = 1, desired = 1 }
  docs          = { instance_type = "t4g.micro", min = 1, max = 1, desired = 1 }
  celery-worker = { instance_type = "t4g.small", min = 1, max = 4, desired = 1 }
  celery-beat   = { instance_type = "t4g.micro", min = 1, max = 1, desired = 1 }
  opa           = { instance_type = "t4g.micro", min = 1, max = 2, desired = 1 }
}

celery_concurrency = 2

postgres_instance_class        = "db.t4g.small"
postgres_allocated_storage     = 20
postgres_multi_az              = false
postgres_backup_retention_days = 7
postgres_deletion_protection   = false

redis_node_type     = "cache.t4g.micro"
redis_replica_count = 0

artifact_bucket_name          = "greensecops-artifacts-staging-CHANGEME"
artifact_bucket_force_destroy = true
access_log_bucket_name        = "greensecops-alb-logs-staging-CHANGEME"
ansible_transfer_bucket_name  = "greensecops-ansible-staging-CHANGEME"

log_retention_days  = 14
deletion_protection = false
alarm_email         = ""

tags = {
  Owner = "platform"
}
