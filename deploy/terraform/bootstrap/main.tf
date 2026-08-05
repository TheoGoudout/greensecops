# One-time, once-per-account groundwork that every environment shares: the
# remote-state bucket, the KMS key that encrypts it, and the ECR repositories
# the images are published to. Kept in its own root because it cannot store its
# state in a bucket it has not created yet.

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = local.tags
  }
}

data "aws_caller_identity" "current" {}

locals {
  tags = merge(var.tags, {
    Project   = var.project
    ManagedBy = "terraform"
    Component = "bootstrap"
  })
}

# --------------------------------------------------------------------------
# KMS
# --------------------------------------------------------------------------

resource "aws_kms_key" "state" {
  description             = "Encrypts the ${var.project} Terraform remote state and ECR repositories."
  enable_key_rotation     = true
  deletion_window_in_days = 30

  tags = merge(local.tags, {
    Name = "${var.project}-bootstrap"
  })
}

resource "aws_kms_alias" "state" {
  name          = "alias/${var.project}-bootstrap"
  target_key_id = aws_kms_key.state.key_id
}

# --------------------------------------------------------------------------
# Remote state bucket
# --------------------------------------------------------------------------

resource "aws_s3_bucket" "state" {
  bucket = var.state_bucket_name

  tags = merge(local.tags, {
    Name = var.state_bucket_name
  })
}

resource "aws_s3_bucket_versioning" "state" {
  bucket = aws_s3_bucket.state.id

  # Non-negotiable for a state bucket: a corrupted or truncated state file is
  # only recoverable from a previous object version.
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "state" {
  bucket = aws_s3_bucket.state.id

  rule {
    apply_server_side_encryption_by_default {
      kms_master_key_id = aws_kms_key.state.arn
      sse_algorithm     = "aws:kms"
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_public_access_block" "state" {
  bucket = aws_s3_bucket.state.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "state" {
  bucket = aws_s3_bucket.state.id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "state" {
  bucket     = aws_s3_bucket.state.id
  depends_on = [aws_s3_bucket_versioning.state]

  rule {
    id     = "expire-noncurrent-state-versions"
    status = "Enabled"

    filter {}

    # Keep enough history to roll back a bad apply without accumulating every
    # version of a file that changes on each run, forever.
    noncurrent_version_expiration {
      noncurrent_days           = 90
      newer_noncurrent_versions = 20
    }

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }
}

data "aws_iam_policy_document" "state_tls_only" {
  statement {
    sid    = "DenyInsecureTransport"
    effect = "Deny"

    principals {
      type        = "*"
      identifiers = ["*"]
    }

    actions = ["s3:*"]
    resources = [
      aws_s3_bucket.state.arn,
      "${aws_s3_bucket.state.arn}/*",
    ]

    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

resource "aws_s3_bucket_policy" "state" {
  bucket = aws_s3_bucket.state.id
  policy = data.aws_iam_policy_document.state_tls_only.json

  # The public-access block must land before a policy is evaluated, otherwise
  # a Deny-only policy can be applied to a briefly-public bucket.
  depends_on = [aws_s3_bucket_public_access_block.state]
}

# --------------------------------------------------------------------------
# Container registry
# --------------------------------------------------------------------------

resource "aws_ecr_repository" "images" {
  for_each = toset(var.ecr_repository_names)

  name = "${var.project}/${each.key}"

  # Deploys push a short git SHA as the tag (deploy-reusable.yml derives it
  # from `git rev-parse --short HEAD`), never a moving tag like `latest` —
  # that one lives in GHCR. So a tag here already names exactly one build, and
  # making that a guarantee is what lets a rollback to a previously-deployed
  # tag be trusted to fetch the image that was deployed under it.
  #
  # The cost is that re-running a build for a commit already pushed fails
  # instead of overwriting. That is the intended behaviour: the rebuilt image
  # would not be byte-identical (dependencies move), so silently repointing
  # the tag is the problem being prevented. To redeploy an existing tag, use
  # the workflow's rollback path, which skips the build entirely.
  image_tag_mutability = "IMMUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "KMS"
    kms_key         = aws_kms_key.state.arn
  }

  tags = merge(local.tags, {
    Name = "${var.project}/${each.key}"
  })
}

resource "aws_ecr_lifecycle_policy" "images" {
  for_each = aws_ecr_repository.images

  repository = each.value.name

  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Expire untagged images after ${var.ecr_untagged_image_expiry_days} days"
      selection = {
        tagStatus   = "untagged"
        countType   = "sinceImagePushed"
        countUnit   = "days"
        countNumber = var.ecr_untagged_image_expiry_days
      }
      action = { type = "expire" }
    }]
  })
}

# --------------------------------------------------------------------------
# GitHub Actions OIDC
# --------------------------------------------------------------------------
# Account-global, so it lives here rather than in the environment root — one
# provider serves staging and production alike. The per-environment roles that
# trust it are created by the cicd module, each scoped to a single GitHub
# environment so a staging deploy cannot obtain production credentials.
#
# This is what keeps long-lived AWS keys out of GitHub secrets entirely: the
# workflow exchanges a short-lived OIDC token for a session at run time.

resource "aws_iam_openid_connect_provider" "github" {
  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]

  # No thumbprint_list: since 2023 IAM validates GitHub's OIDC endpoint against
  # its own trusted root CAs, and a pinned thumbprint only creates a rotation
  # hazard.

  tags = merge(local.tags, {
    Name = "github-actions"
  })
}
