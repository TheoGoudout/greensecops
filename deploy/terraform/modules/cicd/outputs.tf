output "deploy_role_arn" {
  description = "Role GitHub Actions assumes to deploy this environment. Set it as the AWS_DEPLOY_ROLE_ARN variable on the matching GitHub environment."
  value       = aws_iam_role.deploy.arn
}

output "deploy_role_name" {
  description = "Name of the deploy role, for auditing and CloudTrail queries."
  value       = aws_iam_role.deploy.name
}
