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
  single_nat_gateway      = var.single_nat_gateway
  flow_log_retention_days = var.log_retention_days
  tags                    = local.common_tags
}

module "security" {
  source = "./modules/security"

  name_prefix = local.name_prefix
  vpc_id      = module.network.vpc_id
  vpc_cidr    = module.network.vpc_cidr

  services = {
    for role, svc in local.service_topology : role => {
      port     = svc.port
      exposure = svc.exposure
    }
  }

  data_client_roles    = local.data_client_roles
  public_ingress_cidrs = var.public_ingress_cidrs
  tags                 = local.common_tags
}

# --------------------------------------------------------------------------
# Data tier
# --------------------------------------------------------------------------

module "data" {
  source = "./modules/data"

  name_prefix = local.name_prefix
  subnet_ids  = module.network.isolated_subnet_ids

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
  ssm_parameter_prefix = local.ssm_prefix

  roles = {
    for role in keys(local.service_topology) : role => {
      # Only the roles running application code need the secret half of the
      # parameter tree; the static-content containers take plain config only.
      reads_secrets       = contains(local.data_client_roles, role)
      uses_artifact_store = contains(["backend", "celery-worker"], role)

      # Cloud-posture collection runs as a Celery task on the workers and is
      # triggered synchronously from the API, so both need to assume.
      scans_customer_accounts = contains(["backend", "celery-worker"], role)
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

  public_services = {
    for role in local.public_roles : role => {
      port              = local.service_topology[role].port
      health_check_path = local.service_topology[role].health_check_path
      priority          = local.service_topology[role].priority
    }
  }

  internal_service = {
    port              = local.service_topology["opa"].port
    health_check_path = local.service_topology["opa"].health_check_path
  }

  access_log_bucket_name    = var.access_log_bucket_name
  access_log_retention_days = var.artifact_retention_days
  deletion_protection       = var.deletion_protection
  tags                      = local.common_tags
}

# --------------------------------------------------------------------------
# Services
# --------------------------------------------------------------------------
# One module instantiation per role. Everything role-specific lives in
# local.service_topology and var.services, so adding an eighth container is a
# map entry rather than another block.

module "service" {
  source   = "./modules/service"
  for_each = local.service_topology

  name_prefix = local.name_prefix
  role        = each.key

  ami_id                = local.ami_id
  instance_type         = var.services[each.key].instance_type
  instance_profile_name = module.iam.instance_profile_names[each.key]
  subnet_ids            = module.network.private_subnet_ids
  security_group_ids    = [module.security.service_security_group_ids[each.key]]

  user_data = templatefile("${path.module}/modules/service/templates/user_data.sh.tftpl", {
    role        = each.key
    environment = var.environment
  })

  min_size         = var.services[each.key].min
  max_size         = var.services[each.key].max
  desired_capacity = var.services[each.key].desired

  target_group_arns = compact([
    try(module.edge.public_target_group_arns[each.key], ""),
    each.key == "opa" ? module.edge.internal_target_group_arn : "",
  ])

  # Celery scales on CPU because its work is analysis, not requests; OPA scales
  # on request count because policy evaluation is cheap per call but frequent.
  autoscaling = (
    each.key == "celery-worker" ? { metric = "cpu", target_value = var.celery_worker_target_cpu } :
    each.key == "opa" ? { metric = "requests", target_value = var.opa_target_requests_per_instance } :
    null
  )

  alb_arn_suffix          = each.key == "opa" ? module.edge.internal_alb_arn_suffix : module.edge.public_alb_arn_suffix
  target_group_arn_suffix = each.key == "opa" ? module.edge.internal_target_group_arn_suffix : try(module.edge.public_target_group_arn_suffixes[each.key], "")

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

  postgres_instance_id       = "${local.name_prefix}-postgres"
  redis_replication_group_id = "${local.name_prefix}-redis"

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
