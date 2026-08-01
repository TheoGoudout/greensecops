# GreenSecOps on AWS: one Auto Scaling group per service, managed PostgreSQL,
# Redis and object storage, fronted by an internet-facing load balancer that
# routes the four public hostnames by Host header.
#
# This root creates infrastructure only. The instances come up empty; Ansible
# (deploy/ansible) reaches them over SSM Session Manager, renders their .env
# from the Parameter Store tree below, and starts the containers.

# --------------------------------------------------------------------------
# Encryption
# --------------------------------------------------------------------------

data "aws_caller_identity" "current" {}

resource "aws_kms_key" "environment" {
  description             = "Encrypts ${local.name_prefix} storage, secrets, logs and the alarm topic."
  enable_key_rotation     = true
  deletion_window_in_days = 30

  tags = merge(local.common_tags, {
    Name = local.name_prefix
  })
}

resource "aws_kms_alias" "environment" {
  name          = "alias/${local.name_prefix}"
  target_key_id = aws_kms_key.environment.key_id
}

# CloudWatch Logs encrypts with the key on the *service's* behalf, so the key
# policy has to allow it explicitly — an IAM policy on the reader is not enough.
data "aws_iam_policy_document" "environment_key" {
  statement {
    sid       = "AccountRoot"
    effect    = "Allow"
    actions   = ["kms:*"]
    resources = ["*"]

    principals {
      type        = "AWS"
      identifiers = ["arn:aws:iam::${data.aws_caller_identity.current.account_id}:root"]
    }
  }

  statement {
    sid    = "CloudWatchLogs"
    effect = "Allow"

    principals {
      type        = "Service"
      identifiers = ["logs.${var.aws_region}.amazonaws.com"]
    }

    actions = [
      "kms:Encrypt*",
      "kms:Decrypt*",
      "kms:ReEncrypt*",
      "kms:GenerateDataKey*",
      "kms:Describe*",
    ]
    resources = ["*"]

    condition {
      test     = "ArnLike"
      variable = "kms:EncryptionContext:aws:logs:arn"
      values   = ["arn:aws:logs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:log-group:*"]
    }
  }
}

resource "aws_kms_key_policy" "environment" {
  key_id = aws_kms_key.environment.id
  policy = data.aws_iam_policy_document.environment_key.json
}

# --------------------------------------------------------------------------
# Network and security
# --------------------------------------------------------------------------

module "network" {
  source = "./modules/network"

  name_prefix             = local.name_prefix
  vpc_cidr                = var.vpc_cidr
  availability_zones      = local.availability_zones
  nat_gateway_count       = local.nat_gateway_count
  interface_endpoints     = local.interface_endpoints
  flow_log_retention_days = var.log_retention_days
  tags                    = local.common_tags
}

module "security" {
  source = "./modules/security"

  name_prefix = local.name_prefix
  vpc_id      = module.network.vpc_id
  vpc_cidr    = module.network.vpc_cidr

  # Keyed by host group, not by service: a group co-locating the three static
  # sites has to expose all three of their host ports.
  groups = {
    for group, services in local.groups : group => {
      public_ports   = [for svc in local.group_public_services[group] : local.service_topology[svc].host_port]
      internal_ports = [for svc in local.group_internal_services[group] : local.service_topology[svc].host_port]
    }
  }

  data_client_groups     = local.data_client_groups
  managed_database       = local.managed_database
  managed_cache          = local.managed_cache
  internal_load_balancer = local.internal_load_balancer
  public_ingress_cidrs   = var.public_ingress_cidrs
  tags                   = local.common_tags
}

# --------------------------------------------------------------------------
# Data tier
# --------------------------------------------------------------------------

module "data" {
  source = "./modules/data"

  name_prefix = local.name_prefix
  subnet_ids  = module.network.isolated_subnet_ids

  create_managed_database = local.managed_database
  create_managed_cache    = local.managed_cache

  postgres_security_group_id = module.security.postgres_security_group_id
  redis_security_group_id    = module.security.redis_security_group_id
  kms_key_arn                = aws_kms_key.environment.arn

  postgres_instance_class        = var.postgres_instance_class
  postgres_allocated_storage     = var.postgres_allocated_storage
  postgres_multi_az              = var.postgres_multi_az
  postgres_backup_retention_days = var.postgres_backup_retention_days
  postgres_deletion_protection   = var.postgres_deletion_protection

  redis_node_type     = var.redis_node_type
  redis_replica_count = var.redis_replica_count

  artifact_bucket_name          = var.artifact_bucket_name
  artifact_retention_days       = var.artifact_retention_days
  artifact_bucket_force_destroy = var.artifact_bucket_force_destroy

  ansible_transfer_bucket_name = var.ansible_transfer_bucket_name

  log_retention_days = var.log_retention_days
  tags               = local.common_tags
}

# --------------------------------------------------------------------------
# Identity
# --------------------------------------------------------------------------

module "iam" {
  source = "./modules/iam"

  name_prefix          = local.name_prefix
  project              = var.project
  environment          = var.environment
  ssm_parameter_prefix = local.ssm_prefix

  # Permissions are the union of what a group's services need. In single_host
  # that means the one group holds all of them; in distributed the static-site
  # groups hold almost none.
  roles = {
    for group, services in local.groups : group => {
      reads_secrets = local.group_reads_secrets[group]

      # Cloud-posture collection runs as a Celery task on the workers and is
      # triggered synchronously from the API, so both need to assume.
      uses_artifact_store     = local.group_uses_artifacts[group]
      scans_customer_accounts = local.group_uses_artifacts[group]

      # Only a group that self-hosts the data tier attaches the state volume.
      manages_state_volume = local.persistent_volume
    }
  }

  kms_key_arn                 = aws_kms_key.environment.arn
  ecr_repository_arns         = var.ecr_repository_arns
  artifact_bucket_arn         = module.data.artifact_bucket_arn
  ansible_transfer_bucket_arn = module.data.ansible_transfer_bucket_arn
  database_secret_arn         = module.data.postgres_master_secret_arn
  tags                        = local.common_tags
}

# --------------------------------------------------------------------------
# Edge
# --------------------------------------------------------------------------

module "edge" {
  source = "./modules/edge"

  name_prefix        = local.name_prefix
  vpc_id             = module.network.vpc_id
  public_subnet_ids  = module.network.public_subnet_ids
  private_subnet_ids = module.network.private_subnet_ids

  public_alb_security_group_id   = module.security.public_alb_security_group_id
  internal_alb_security_group_id = module.security.internal_alb_security_group_id

  route53_zone_id = var.route53_zone_id
  domain_name     = var.domain_name
  hostnames       = local.hostnames

  # Target groups stay per service even when several share a host — that is
  # what lets a host-header rule reach the right container, by targeting the
  # host port it publishes.
  public_services = {
    for svc, cfg in local.public_services : svc => {
      port              = cfg.host_port
      health_check_path = cfg.health_check_path
      priority          = cfg.priority
    }
  }

  internal_service = local.internal_load_balancer ? {
    port              = local.service_topology["opa"].host_port
    health_check_path = local.service_topology["opa"].health_check_path
  } : null

  access_log_bucket_name    = var.access_log_bucket_name
  access_log_retention_days = var.artifact_retention_days
  deletion_protection       = var.deletion_protection
  tags                      = local.common_tags
}

# --------------------------------------------------------------------------
# Persistent state (single_host only)
# --------------------------------------------------------------------------

module "state_volume" {
  source = "./modules/state_volume"
  count  = local.persistent_volume ? 1 : 0

  name_prefix = local.name_prefix

  # Pinned to the first zone, and the host group with it: an EBS volume cannot
  # cross availability zones. This is the concrete reason single_host has no
  # redundancy, and the first thing `consolidated` fixes.
  availability_zone = local.availability_zones[0]

  size               = var.state_volume_size
  snapshot_retention = var.state_volume_snapshot_retention
  kms_key_arn        = aws_kms_key.environment.arn
  tags               = local.common_tags
}

# --------------------------------------------------------------------------
# Host groups
# --------------------------------------------------------------------------
# One module instantiation per group. What varies between topologies is only
# how many groups there are and which services each runs — the module itself is
# identical whether it is running one container or seven.

module "service" {
  source   = "./modules/service"
  for_each = local.groups

  name_prefix = local.name_prefix
  role        = each.key
  services    = each.value

  ami_id                = local.ami_id
  instance_type         = var.groups[each.key].instance_type
  instance_profile_name = module.iam.instance_profile_names[each.key]

  # With no NAT gateway the private subnets have no route out, so the instances
  # sit in the public tier with a public address instead. Inbound is still shut
  # by the security group; this only buys egress.
  subnet_ids         = local.instance_subnet_ids
  assign_public_ip   = local.instances_are_public
  security_group_ids = [module.security.group_security_group_ids[each.key]]

  user_data = templatefile("${path.module}/modules/service/templates/user_data.sh.tftpl", {
    role        = each.key
    environment = var.environment
    services    = join(",", each.value)

    # Only the group that self-hosts the data tier claims the volume.
    state_volume_tag = local.persistent_volume ? local.name_prefix : ""
  })

  min_size         = var.groups[each.key].min
  max_size         = var.groups[each.key].max
  desired_capacity = var.groups[each.key].desired

  target_group_arns = concat(
    [for svc in local.group_public_services[each.key] : module.edge.public_target_group_arns[svc]],
    local.internal_load_balancer && length(local.group_internal_services[each.key]) > 0
    ? [module.edge.internal_target_group_arn]
    : [],
  )

  # Only meaningful where a service has a group to itself. A consolidated
  # `worker` group scales on CPU; a single_host group scales not at all.
  autoscaling = lookup(local.scaling_policies, each.key, null)

  alb_arn_suffix          = lookup(local.group_alb_arn_suffix, each.key, module.edge.public_alb_arn_suffix)
  target_group_arn_suffix = lookup(local.group_target_group_arn_suffix, each.key, "")

  kms_key_arn        = aws_kms_key.environment.arn
  log_retention_days = var.log_retention_days
  tags               = local.common_tags
}

# --------------------------------------------------------------------------
# Observability
# --------------------------------------------------------------------------

module "observability" {
  source = "./modules/observability"

  name_prefix = local.name_prefix
  alarm_email = var.alarm_email

  autoscaling_group_names          = { for role, svc in module.service : role => svc.autoscaling_group_name }
  public_alb_arn_suffix            = module.edge.public_alb_arn_suffix
  public_target_group_arn_suffixes = module.edge.public_target_group_arn_suffixes

  # Empty in single_host, where there is no RDS or ElastiCache to alarm on —
  # the containers are covered by the group's CPU and disk alarms instead.
  postgres_instance_id       = local.managed_database ? "${local.name_prefix}-postgres" : ""
  redis_replication_group_id = local.managed_cache ? "${local.name_prefix}-redis" : ""

  kms_key_arn = aws_kms_key.environment.arn
  tags        = local.common_tags
}

# --------------------------------------------------------------------------
# Deploy identity
# --------------------------------------------------------------------------

module "cicd" {
  source = "./modules/cicd"
  count  = var.github_oidc_provider_arn == "" ? 0 : 1

  name_prefix = local.name_prefix
  project     = var.project
  environment = var.environment

  github_repository        = var.github_repository
  github_oidc_provider_arn = var.github_oidc_provider_arn

  ssm_parameter_prefix = local.ssm_prefix

  # The only two parameters the pipeline may write, and the only two secrets it
  # may read — both public identifiers the frontend bundle embeds anyway.
  deployable_tag_parameters   = ["IMAGE_TAG", "PREVIOUS_IMAGE_TAG"]
  build_identifier_parameters = ["GITHUB_APP_NAME", "GITHUB_CLIENT_ID"]

  ecr_repository_arns         = var.ecr_repository_arns
  ansible_transfer_bucket_arn = module.data.ansible_transfer_bucket_arn
  kms_key_arn                 = aws_kms_key.environment.arn
  tags                        = local.common_tags
}
