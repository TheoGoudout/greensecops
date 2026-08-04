# "After" reference: the hardened counterpart to aws-s3-static-site. Private
# ACL, versioning enabled, and fully tagged. This module must stay violation-
# free across the WHOLE rule suite — it is the Terraform equivalent of
# examples/deploy.yml, so it can't silently drift as new rules land.

terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  # A root module keeps its state remotely: the local default has no locking,
  # no history, and holds every resource attribute including the sensitive
  # ones.
  backend "s3" {
    bucket       = "example-tfstate"
    key          = "assets/terraform.tfstate"
    region       = "eu-west-1"
    encrypt      = true
    use_lockfile = true
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
  acl    = "private"

  versioning {
    enabled = true
  }

  tags = local.common_tags
}

# The account-level backstop that makes a public ACL or bucket policy fail
# closed, whatever anything else later sets. All four settings matter: each
# closes a different route to public.
resource "aws_s3_bucket_public_access_block" "assets" {
  bucket = aws_s3_bucket.assets.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}
