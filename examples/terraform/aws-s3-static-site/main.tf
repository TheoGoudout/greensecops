# "Before" example: a public static-site bucket of the kind found in many
# early-stage project repos. GreenSecOps flags it for a public ACL, no
# versioning and no cost/ownership tags. See expected.yaml for the exact rules
# this module is asserted to trip.

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

resource "aws_s3_bucket" "static_site" {
  bucket = "${var.project}-static-site"

  # World-readable objects — anyone on the internet can read the bucket.
  acl = "public-read"

  # No `versioning {}` block: an accidental overwrite or delete is unrecoverable.
  # No `tags = {}`: cost and ownership can't be attributed.
}
