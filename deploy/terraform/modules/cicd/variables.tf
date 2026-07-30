variable "name_prefix" {
  description = "Prefix applied to every resource name, e.g. greensecops-production."
  type        = string
}

variable "project" {
  description = "Project slug, matched against the Project tag when scoping Session Manager access."
  type        = string
}

variable "environment" {
  description = "Environment this role deploys to. Also the GitHub environment name the OIDC subject is pinned to, so a staging deploy cannot obtain production credentials."
  type        = string
}

variable "github_repository" {
  description = "Repository allowed to assume this role, as owner/name."
  type        = string
}

variable "github_oidc_provider_arn" {
  description = "ARN of the account's GitHub Actions OIDC provider, as output by the bootstrap root."
  type        = string
}

variable "ssm_parameter_prefix" {
  description = "Parameter Store path holding this environment's configuration, e.g. /greensecops/production."
  type        = string
}

variable "deployable_tag_parameters" {
  description = "Names of the Parameter Store entries the pipeline may write — the current and previous image tags, and nothing else."
  type        = list(string)
}

variable "build_identifier_parameters" {
  description = "Names of the SecureString parameters the build step may read. These are public identifiers baked into the frontend bundle, not credentials; the role gets no access to the rest of the secret tree."
  type        = list(string)
}

variable "ecr_repository_arns" {
  description = "ARNs of the ECR repositories the pipeline pushes images to."
  type        = list(string)
}

variable "ansible_transfer_bucket_arn" {
  description = "ARN of the bucket Ansible's aws_ssm connection plugin stages files through."
  type        = string
}

variable "kms_key_arn" {
  description = "Customer-managed KMS key encrypting the parameters and the transfer bucket."
  type        = string
}

variable "tags" {
  description = "Tags applied to every resource in this module."
  type        = map(string)
}
