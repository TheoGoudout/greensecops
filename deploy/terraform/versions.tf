terraform {
  # 1.10 is the floor for S3 native state locking (`use_lockfile`), which
  # replaces the DynamoDB lock table older setups need.
  required_version = ">= 1.10.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }
}
