variable "project" {
  description = "Project slug used as the prefix for every bootstrap resource name."
  type        = string
  default     = "greensecops"
}

variable "aws_region" {
  description = "AWS region the state bucket, KMS key and ECR repositories live in."
  type        = string
}

variable "state_bucket_name" {
  description = "Globally unique name for the Terraform remote-state bucket. Must match the `bucket` set in deploy/terraform/env/<env>.backend.hcl."
  type        = string
}

variable "ecr_repository_names" {
  description = "Container images GreenSecOps deploys, one ECR repository each. Must stay in sync with the image list in deploy/ansible/vars/services.yml."
  type        = list(string)
  default     = ["backend", "frontend", "landing", "docs", "opa"]
}

variable "ecr_untagged_image_expiry_days" {
  description = "Days before an untagged image layer is expired from ECR by the lifecycle policy."
  type        = number
  default     = 14
}

variable "tags" {
  description = "Extra tags merged into every bootstrap resource on top of the built-in Project/ManagedBy pair."
  type        = map(string)
  default     = {}
}
