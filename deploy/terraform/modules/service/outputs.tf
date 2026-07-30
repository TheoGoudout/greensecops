output "autoscaling_group_name" {
  description = "Name of the Auto Scaling group, used by the CloudWatch alarms."
  value       = aws_autoscaling_group.this.name
}

output "launch_template_id" {
  description = "ID of the launch template backing the group."
  value       = aws_launch_template.this.id
}

output "log_group_name" {
  description = "CloudWatch log group this service's containers ship to."
  value       = aws_cloudwatch_log_group.this.name
}
