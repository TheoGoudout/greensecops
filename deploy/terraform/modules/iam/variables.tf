variable "name_prefix" {
  description = "Prefix applied to every role and policy name, e.g. greensecops-production."
  type        = string
}

variable "project" {
  description = "Project slug, matched against the Project tag when scoping volume attachment."
  type        = string
}

variable "environment" {
  description = "Environment name, matched against the Environment tag when scoping volume attachment."
  type        = string
}

variable "ssm_parameter_prefix" {
  description = "Parameter Store path holding this environment's configuration, e.g. /greensecops/production."
  type        = string
}

variable "roles" {
  description = "Every host group. `reads_secrets` grants the SecureString half of the parameter tree and the database password; `scans_customer_accounts` grants sts:AssumeRole for cloud-posture collection."
  type = map(object({
    reads_secrets           = optional(bool, false)
    scans_customer_accounts = optional(bool, false)
    manages_state_volume    = optional(bool, false)
  }))
}

variable "kms_key_arn" {
  description = "Customer-managed KMS key that encrypts the parameters and the database secret."
  type        = string
}

variable "ecr_repository_arns" {
  description = "ARNs of the ECR repositories instances may pull from, as output by the bootstrap root."
  type        = list(string)
}

variable "database_secret_arn" {
  description = "ARN of the RDS-managed Secrets Manager secret holding the database master password."
  type        = string
}

variable "tags" {
  description = "Tags applied to every resource in this module."
  type        = map(string)
}

variable "ansible_transfer_bucket_arn" {
  description = "ARN of the bucket Ansible's aws_ssm connection plugin stages files through. Every role needs it — it is how the deploy playbook reaches the host at all."
  type        = string
}
