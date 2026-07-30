terraform {
  # 1.10 is the floor for S3 native state locking (`use_lockfile`), which the
  # main root uses instead of a DynamoDB lock table.
  required_version = ">= 1.10.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }

  # Deliberately no backend block: this root *creates* the bucket every other
  # root stores its state in, so its own state starts out local. Commit the
  # resulting terraform.tfstate to a secure location (or migrate it into the
  # bucket it just created with `terraform init -migrate-state` once the
  # backend block below is uncommented).
}
