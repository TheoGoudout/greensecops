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
