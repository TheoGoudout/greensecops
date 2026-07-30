# The same hardened bucket as aws-s3-hardened, written against a modern AWS
# provider. Since provider v4 the bucket sub-resources are separate resources
# rather than inline blocks, so versioning lives in aws_s3_bucket_versioning.
# This module must stay violation-free across the WHOLE rule suite: it is the
# regression guard for s3_bucket_missing_versioning understanding the split
# form, which it used to report as a false positive.

terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }
}

provider "aws" {
  region = var.region
}

locals {
  common_tags = {
    Team        = "platform"
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

resource "aws_s3_bucket" "assets" {
  bucket = "${var.project}-assets"

  tags = local.common_tags
}

resource "aws_s3_bucket_versioning" "assets" {
  bucket = aws_s3_bucket.assets.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_public_access_block" "assets" {
  bucket = aws_s3_bucket.assets.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "assets" {
  bucket = aws_s3_bucket.assets.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}
