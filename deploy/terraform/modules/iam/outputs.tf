output "instance_profile_names" {
  description = "Instance profile name for each service role, keyed by role."
  value       = { for role, profile in aws_iam_instance_profile.service : role => profile.name }
}

output "role_arns" {
  description = "Instance role ARN for each service role, keyed by role. The backend's ARN is what customers name in the trust policy of their cloud-posture role."
  value       = { for role, iam_role in aws_iam_role.service : role => iam_role.arn }
}
