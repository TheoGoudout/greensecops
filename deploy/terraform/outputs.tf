output "environment" {
  description = "Environment this state manages. Ansible filters its dynamic inventory on the matching Environment tag."
  value       = var.environment
}

output "aws_region" {
  description = "Region the environment is deployed in. Pass it to Ansible as the inventory's region."
  value       = var.aws_region
}

output "urls" {
  description = "Public URL of each user-facing service."
  value       = local.urls
}

output "ssm_parameter_prefix" {
  description = "Parameter Store path holding this environment's configuration. Seed the secrets under <prefix>/secret/."
  value       = local.ssm_prefix
}

output "unseeded_secret_parameters" {
  description = "Every SecureString parameter that must be seeded before the first deploy, in the order deploy/README.md lists them."
  value       = sort([for name in keys(local.secret_parameters) : "${local.ssm_prefix}/secret/${name}"])
}

output "ecr_registry" {
  description = "Registry the deploy playbook pushes images to and instances pull from."
  value       = var.ecr_registry
}

output "backend_role_arn" {
  description = "IAM role the backend runs as. Customers name this ARN in the trust policy of the role they create for cloud-posture scanning."
  value       = module.iam.role_arns["backend"]
}

output "github_webhook_url" {
  description = "URL to configure as the GitHub App's webhook endpoint after the first apply."
  value       = "${local.urls.backend}/api/v1/webhooks/github"
}

output "github_oauth_callback_url" {
  description = "URL to configure as the GitHub OAuth App's authorization callback. The backend derives it from FRONTEND_HOST and it is not separately configurable."
  value       = "${local.urls.frontend}/auth/github/callback"
}

output "alarm_topic_arn" {
  description = "SNS topic every CloudWatch alarm publishes to."
  value       = module.observability.alarm_topic_arn
}

output "database_secret_arn" {
  description = "Secrets Manager secret holding the database master password, managed and rotated by RDS."
  value       = module.data.postgres_master_secret_arn
}

output "autoscaling_group_names" {
  description = "Auto Scaling group name for each service role."
  value       = { for role, svc in module.service : role => svc.autoscaling_group_name }
}

output "ansible_transfer_bucket" {
  description = "Bucket Ansible's aws_ssm connection plugin stages files through. Set it as ansible_aws_ssm_bucket_name, or let group_vars/all.yml read it from Parameter Store."
  value       = module.data.ansible_transfer_bucket_name
}

output "github_deploy_role_arn" {
  description = "Role GitHub Actions assumes to deploy this environment. Set it as the AWS_DEPLOY_ROLE_ARN variable on the GitHub environment of the same name; empty when github_oidc_provider_arn was not supplied."
  value       = try(module.cicd[0].deploy_role_arn, "")
}
