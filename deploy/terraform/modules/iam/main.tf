# One instance role per service rather than one shared role, so the blast
# radius of a compromised landing-page container is a landing-page container.
# Only the backend and the Celery workers can read secrets or assume a
# customer's cloud-posture role.

data "aws_caller_identity" "current" {}
data "aws_partition" "current" {}
data "aws_region" "current" {}

locals {
  secret_readers   = { for role, cfg in var.roles : role => cfg if cfg.reads_secrets }
  account_scanners = { for role, cfg in var.roles : role => cfg if cfg.scans_customer_accounts }
  volume_managers  = { for role, cfg in var.roles : role => cfg if cfg.manages_state_volume }
}

data "aws_iam_policy_document" "ec2_assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "service" {
  for_each = var.roles

  name                 = "${var.name_prefix}-${each.key}"
  description          = "Instance role for the GreenSecOps ${each.key} service."
  assume_role_policy   = data.aws_iam_policy_document.ec2_assume.json
  max_session_duration = 3600

  tags = merge(var.tags, {
    Name               = "${var.name_prefix}-${each.key}"
    "greensecops:role" = each.key
  })
}

resource "aws_iam_instance_profile" "service" {
  for_each = var.roles

  name = "${var.name_prefix}-${each.key}"
  role = aws_iam_role.service[each.key].name

  tags = var.tags
}

# --------------------------------------------------------------------------
# Baseline: SSM (Ansible's transport) and the CloudWatch agent
# --------------------------------------------------------------------------

resource "aws_iam_role_policy_attachment" "ssm_core" {
  for_each = var.roles

  role       = aws_iam_role.service[each.key].name
  policy_arn = "arn:${data.aws_partition.current.partition}:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_role_policy_attachment" "cloudwatch_agent" {
  for_each = var.roles

  role       = aws_iam_role.service[each.key].name
  policy_arn = "arn:${data.aws_partition.current.partition}:iam::aws:policy/CloudWatchAgentServerPolicy"
}

# --------------------------------------------------------------------------
# Image pulls
# --------------------------------------------------------------------------

data "aws_iam_policy_document" "ecr_pull" {
  # GetAuthorizationToken is account-wide by design — it takes no resource.
  statement {
    sid       = "EcrAuth"
    effect    = "Allow"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }

  statement {
    sid    = "EcrPull"
    effect = "Allow"
    actions = [
      "ecr:BatchCheckLayerAvailability",
      "ecr:BatchGetImage",
      "ecr:GetDownloadUrlForLayer",
    ]
    resources = var.ecr_repository_arns
  }
}

resource "aws_iam_policy" "ecr_pull" {
  name        = "${var.name_prefix}-ecr-pull"
  description = "Pull GreenSecOps images from the project's ECR repositories."
  policy      = data.aws_iam_policy_document.ecr_pull.json

  tags = var.tags
}

resource "aws_iam_role_policy_attachment" "ecr_pull" {
  for_each = var.roles

  role       = aws_iam_role.service[each.key].name
  policy_arn = aws_iam_policy.ecr_pull.arn
}

# --------------------------------------------------------------------------
# Configuration: the non-secret half of the parameter tree
# --------------------------------------------------------------------------

data "aws_iam_policy_document" "config_read" {
  statement {
    sid    = "ReadPlainConfig"
    effect = "Allow"
    actions = [
      "ssm:GetParameter",
      "ssm:GetParameters",
      "ssm:GetParametersByPath",
    ]
    resources = [
      "arn:${data.aws_partition.current.partition}:ssm:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:parameter${var.ssm_parameter_prefix}/config",
      "arn:${data.aws_partition.current.partition}:ssm:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:parameter${var.ssm_parameter_prefix}/config/*",
    ]
  }
}

resource "aws_iam_policy" "config_read" {
  name        = "${var.name_prefix}-config-read"
  description = "Read the non-secret configuration parameters for this environment."
  policy      = data.aws_iam_policy_document.config_read.json

  tags = var.tags
}

resource "aws_iam_role_policy_attachment" "config_read" {
  for_each = var.roles

  role       = aws_iam_role.service[each.key].name
  policy_arn = aws_iam_policy.config_read.arn
}

# --------------------------------------------------------------------------
# Secrets: only the roles that run application code needing them
# --------------------------------------------------------------------------

data "aws_iam_policy_document" "secret_read" {
  statement {
    sid    = "ReadSecureParameters"
    effect = "Allow"
    actions = [
      "ssm:GetParameter",
      "ssm:GetParameters",
      "ssm:GetParametersByPath",
    ]
    resources = [
      "arn:${data.aws_partition.current.partition}:ssm:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:parameter${var.ssm_parameter_prefix}/secret",
      "arn:${data.aws_partition.current.partition}:ssm:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:parameter${var.ssm_parameter_prefix}/secret/*",
    ]
  }

  statement {
    sid       = "ReadDatabasePassword"
    effect    = "Allow"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [var.database_secret_arn]
  }

  # Both stores hand back ciphertext; without this the reads above return
  # AccessDeniedException from KMS rather than from SSM.
  statement {
    sid       = "DecryptWithEnvironmentKey"
    effect    = "Allow"
    actions   = ["kms:Decrypt"]
    resources = [var.kms_key_arn]
  }
}

resource "aws_iam_policy" "secret_read" {
  name        = "${var.name_prefix}-secret-read"
  description = "Read the SecureString parameters and the database password for this environment."
  policy      = data.aws_iam_policy_document.secret_read.json

  tags = var.tags
}

resource "aws_iam_role_policy_attachment" "secret_read" {
  for_each = local.secret_readers

  role       = aws_iam_role.service[each.key].name
  policy_arn = aws_iam_policy.secret_read.arn
}


# --------------------------------------------------------------------------
# Customer cloud-posture scanning
# --------------------------------------------------------------------------

data "aws_iam_policy_document" "assume_customer_roles" {
  # Unavoidably unscoped: app/services/cloud/aws_collector.py assumes a role
  # ARN supplied by each customer at connect time, in an account this
  # deployment has never seen. The trust direction is what constrains it —
  # the customer's role must name this account AND match the per-customer
  # ExternalId before the call succeeds, so a wildcard here grants nothing
  # that a customer has not separately allowed.
  statement {
    sid       = "AssumeCustomerScanRoles"
    effect    = "Allow"
    actions   = ["sts:AssumeRole"]
    resources = ["*"]
  }
}

resource "aws_iam_policy" "assume_customer_roles" {
  name        = "${var.name_prefix}-assume-customer-roles"
  description = "Assume the cross-account roles customers grant for cloud-posture scanning."
  policy      = data.aws_iam_policy_document.assume_customer_roles.json

  tags = var.tags
}

resource "aws_iam_role_policy_attachment" "assume_customer_roles" {
  for_each = local.account_scanners

  role       = aws_iam_role.service[each.key].name
  policy_arn = aws_iam_policy.assume_customer_roles.arn
}

# --------------------------------------------------------------------------
# Ansible file transfer
# --------------------------------------------------------------------------

data "aws_iam_policy_document" "ansible_transfer" {
  statement {
    sid       = "ListTransferBucket"
    effect    = "Allow"
    actions   = ["s3:ListBucket", "s3:GetBucketLocation"]
    resources = [var.ansible_transfer_bucket_arn]
  }

  statement {
    sid    = "StageFiles"
    effect = "Allow"
    actions = [
      "s3:GetObject",
      "s3:PutObject",
      "s3:DeleteObject",
      "s3:AbortMultipartUpload",
    ]
    resources = ["${var.ansible_transfer_bucket_arn}/*"]
  }

  statement {
    sid       = "UseTransferBucketEncryptionKey"
    effect    = "Allow"
    actions   = ["kms:Decrypt", "kms:GenerateDataKey"]
    resources = [var.kms_key_arn]
  }
}

resource "aws_iam_policy" "ansible_transfer" {
  name        = "${var.name_prefix}-ansible-transfer"
  description = "Stage files through the Ansible transfer bucket, which is how the aws_ssm connection plugin copies anything onto a host."
  policy      = data.aws_iam_policy_document.ansible_transfer.json

  tags = var.tags
}

resource "aws_iam_role_policy_attachment" "ansible_transfer" {
  for_each = var.roles

  role       = aws_iam_role.service[each.key].name
  policy_arn = aws_iam_policy.ansible_transfer.arn
}

# --------------------------------------------------------------------------
# Persistent state volume
# --------------------------------------------------------------------------
# Only the single_host topology self-hosts PostgreSQL, Redis and object
# storage. Its instance attaches the state volume itself at boot, because an
# Auto Scaling group's launch template cannot know which volume a replacement
# instance should claim.

data "aws_iam_policy_document" "attach_state_volume" {
  statement {
    sid    = "DiscoverStateVolume"
    effect = "Allow"
    actions = [
      "ec2:DescribeVolumes",
      "ec2:DescribeTags",
    ]
    resources = ["*"]
  }

  # Scoped by tag on the volume side, so this cannot attach an arbitrary volume
  # — only the one belonging to this environment.
  statement {
    sid     = "AttachStateVolume"
    effect  = "Allow"
    actions = ["ec2:AttachVolume", "ec2:DetachVolume"]
    resources = [
      "arn:${data.aws_partition.current.partition}:ec2:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:volume/*",
      "arn:${data.aws_partition.current.partition}:ec2:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:instance/*",
    ]

    condition {
      test     = "StringEquals"
      variable = "ec2:ResourceTag/Project"
      values   = [var.project]
    }

    condition {
      test     = "StringEquals"
      variable = "ec2:ResourceTag/Environment"
      values   = [var.environment]
    }
  }
}

resource "aws_iam_policy" "attach_state_volume" {
  count = length(local.volume_managers) > 0 ? 1 : 0

  name        = "${var.name_prefix}-attach-state-volume"
  description = "Discover and attach the environment's persistent state volume at boot."
  policy      = data.aws_iam_policy_document.attach_state_volume.json

  tags = var.tags
}

resource "aws_iam_role_policy_attachment" "attach_state_volume" {
  for_each = local.volume_managers

  role       = aws_iam_role.service[each.key].name
  policy_arn = aws_iam_policy.attach_state_volume[0].arn
}
