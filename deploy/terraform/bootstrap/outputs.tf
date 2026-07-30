output "state_bucket" {
  description = "Name of the Terraform remote-state bucket. Use it as `bucket` in deploy/terraform/env/<env>.backend.hcl."
  value       = aws_s3_bucket.state.id
}

output "state_kms_key_arn" {
  description = "ARN of the KMS key encrypting the state bucket. Use it as `kms_key_id` in deploy/terraform/env/<env>.backend.hcl."
  value       = aws_kms_key.state.arn
}

output "ecr_registry" {
  description = "Registry hostname the images are pushed to. Pass it to the main root as `ecr_registry`."
  value       = "${data.aws_caller_identity.current.account_id}.dkr.ecr.${var.aws_region}.amazonaws.com"
}

output "ecr_repository_urls" {
  description = "Full pull URL of every image repository, keyed by image name."
  value       = { for name, repo in aws_ecr_repository.images : name => repo.repository_url }
}

output "ecr_repository_arns" {
  description = "ARNs of the image repositories. Pass them to the main root as `ecr_repository_arns` so instance roles can be scoped to exactly these."
  value       = [for repo in aws_ecr_repository.images : repo.arn]
}

output "github_oidc_provider_arn" {
  description = "ARN of the GitHub Actions OIDC provider. Pass it to the environment root as `github_oidc_provider_arn`."
  value       = aws_iam_openid_connect_provider.github.arn
}
