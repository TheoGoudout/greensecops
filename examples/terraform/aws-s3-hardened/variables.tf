variable "region" {
  description = "AWS region the bucket is created in."
  type        = string
  default     = "us-east-1"
}

variable "project" {
  description = "Project name used as the bucket-name prefix."
  type        = string
  default     = "acme"
}

variable "environment" {
  description = "Deployment environment (e.g. dev, staging, prod) used for tagging."
  type        = string
  default     = "prod"
}
