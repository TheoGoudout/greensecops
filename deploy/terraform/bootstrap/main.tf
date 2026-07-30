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

  name                 = "${var.project}/${each.key}"
  image_tag_mutability = "MUTABLE"

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
