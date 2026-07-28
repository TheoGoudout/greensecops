variable "region" {
  description = "AWS region the static-site bucket is created in."
  type        = string
  default     = "us-east-1"
}

variable "project" {
  description = "Project name used as the bucket-name prefix."
  type        = string
  default     = "acme"
}
