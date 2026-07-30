# The identity GitHub Actions assumes to deploy this environment.
#
# Two properties matter. First, there are no long-lived AWS keys anywhere: the
# workflow exchanges a short-lived OIDC token for a session at run time.
# Second, the trust policy pins the token's `sub` claim to a single GitHub
# environment, so the production role can only be assumed by a job that
# declared `environment: production` — which is what puts the deployment behind
# that environment's approval rules. A workflow that omits the declaration, or
# names staging, cannot reach production credentials at all.

data "aws_caller_identity" "current" {}
data "aws_partition" "current" {}
data "aws_region" "current" {}

locals {
  parameter_arn_prefix = "arn:${data.aws_partition.current.partition}:ssm:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:parameter"

  # The IAM policy variable ${aws:userid}, assembled rather than written
  # literally. python-hcl2 — which scripts/validate_deploy_terraform.py uses to
  # scan this directory — does not honour Terraform's $$ escape and trips on
  # the colon inside the braces, which would leave this file unparseable and
  # therefore silently unscanned. format() output is never re-interpolated, so
  # this reaches IAM as exactly the variable it looks like.
  own_session_variable = format("%s{aws:userid}", "$")

  tag_parameter_arns = [
    for name in var.deployable_tag_parameters :
    "${local.parameter_arn_prefix}${var.ssm_parameter_prefix}/config/${name}"
  ]

  build_identifier_arns = [
    for name in var.build_identifier_parameters :
    "${local.parameter_arn_prefix}${var.ssm_parameter_prefix}/secret/${name}"
  ]
}

data "aws_iam_policy_document" "github_assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [var.github_oidc_provider_arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    # The environment-scoped subject. Not a wildcard on the repository: a
    # branch or pull-request workflow produces a different `sub` and is
    # rejected, so only a job gated on this GitHub environment can assume.
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:${var.github_repository}:environment:${var.environment}"]
    }
  }
}

resource "aws_iam_role" "deploy" {
  name                 = "${var.name_prefix}-github-deploy"
  description          = "Assumed by GitHub Actions to deploy the ${var.environment} environment."
  assume_role_policy   = data.aws_iam_policy_document.github_assume.json
  max_session_duration = 3600

  tags = merge(var.tags, {
    Name = "${var.name_prefix}-github-deploy"
  })
}

data "aws_iam_policy_document" "deploy" {
  # ---- Images -----------------------------------------------------------
  statement {
    sid       = "EcrAuth"
    effect    = "Allow"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }

  statement {
    sid    = "EcrPushAndPull"
    effect = "Allow"
    actions = [
      "ecr:BatchCheckLayerAvailability",
      "ecr:BatchGetImage",
      "ecr:CompleteLayerUpload",
      "ecr:DescribeImages",
      "ecr:GetDownloadUrlForLayer",
      "ecr:InitiateLayerUpload",
      "ecr:ListImages",
      "ecr:PutImage",
      "ecr:UploadLayerPart",
    ]
    resources = var.ecr_repository_arns
  }

  # ---- Configuration ----------------------------------------------------
  statement {
    sid    = "ReadPlainConfig"
    effect = "Allow"
    actions = [
      "ssm:GetParameter",
      "ssm:GetParameters",
      "ssm:GetParametersByPath",
    ]
    resources = [
      "${local.parameter_arn_prefix}${var.ssm_parameter_prefix}/config",
      "${local.parameter_arn_prefix}${var.ssm_parameter_prefix}/config/*",
    ]
  }

  # Write access is limited to the two tag pointers. The pipeline records what
  # is deployed and what was deployed before it; it cannot rewrite an endpoint,
  # a bucket name, or anything else Terraform owns.
  statement {
    sid       = "RecordDeployedTag"
    effect    = "Allow"
    actions   = ["ssm:PutParameter"]
    resources = local.tag_parameter_arns
  }

  # Named individually rather than by path: the build bakes the GitHub App slug
  # and OAuth client ID into the frontend bundle, so CI needs exactly those two
  # and none of the real secrets beside them.
  statement {
    sid       = "ReadBuildIdentifiers"
    effect    = "Allow"
    actions   = ["ssm:GetParameter", "ssm:GetParameters"]
    resources = local.build_identifier_arns
  }

  statement {
    sid       = "DecryptParameters"
    effect    = "Allow"
    actions   = ["kms:Decrypt", "kms:GenerateDataKey"]
    resources = [var.kms_key_arn]
  }

  # ---- Reaching the instances -------------------------------------------
  statement {
    sid    = "DiscoverInstances"
    effect = "Allow"
    actions = [
      "ec2:DescribeInstances",
      "ec2:DescribeInstanceStatus",
      "ec2:DescribeTags",
      "ssm:DescribeInstanceInformation",
      "ssm:DescribeSessions",
      "autoscaling:DescribeAutoScalingGroups",
      "autoscaling:DescribeAutoScalingInstances",
      "elasticloadbalancing:DescribeTargetGroups",
      "elasticloadbalancing:DescribeTargetHealth",
    ]
    resources = ["*"]
  }

  # Session Manager is the transport Ansible uses. Scoped by tag, so this role
  # can only open a session to instances belonging to its own environment.
  statement {
    sid       = "StartSessionOnEnvironmentInstances"
    effect    = "Allow"
    actions   = ["ssm:StartSession"]
    resources = ["arn:${data.aws_partition.current.partition}:ec2:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:instance/*"]

    condition {
      test     = "StringEquals"
      variable = "ssm:resourceTag/Project"
      values   = [var.project]
    }

    condition {
      test     = "StringEquals"
      variable = "ssm:resourceTag/Environment"
      values   = [var.environment]
    }
  }

  statement {
    sid       = "StartSessionDocument"
    effect    = "Allow"
    actions   = ["ssm:StartSession"]
    resources = ["arn:${data.aws_partition.current.partition}:ssm:${data.aws_region.current.region}::document/AWS-StartSession"]
  }

  # Only this role's own sessions: the policy variable resolves to the
  # assumed-role session at evaluation time, so one run cannot terminate
  # another's.
  statement {
    sid       = "ManageOwnSessions"
    effect    = "Allow"
    actions   = ["ssm:TerminateSession", "ssm:ResumeSession"]
    resources = ["arn:${data.aws_partition.current.partition}:ssm:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:session/${local.own_session_variable}-*"]
  }

  statement {
    sid       = "StageFilesForAnsible"
    effect    = "Allow"
    actions   = ["s3:ListBucket", "s3:GetBucketLocation"]
    resources = [var.ansible_transfer_bucket_arn]
  }

  statement {
    sid    = "TransferFiles"
    effect = "Allow"
    actions = [
      "s3:GetObject",
      "s3:PutObject",
      "s3:DeleteObject",
      "s3:AbortMultipartUpload",
    ]
    resources = ["${var.ansible_transfer_bucket_arn}/*"]
  }
}

resource "aws_iam_policy" "deploy" {
  name        = "${var.name_prefix}-github-deploy"
  description = "Build, publish and roll out GreenSecOps images for the ${var.environment} environment."
  policy      = data.aws_iam_policy_document.deploy.json

  tags = var.tags
}

resource "aws_iam_role_policy_attachment" "deploy" {
  role       = aws_iam_role.deploy.name
  policy_arn = aws_iam_policy.deploy.arn
}
