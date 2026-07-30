output "public_alb_dns_name" {
  description = "DNS name of the internet-facing load balancer."
  value       = aws_lb.public.dns_name
}

output "public_alb_arn_suffix" {
  description = "ARN suffix of the internet-facing load balancer, for CloudWatch metric dimensions and request-count scaling."
  value       = aws_lb.public.arn_suffix
}

output "internal_alb_dns_name" {
  description = "DNS name of the internal load balancer. Becomes OPA_URL's host for the backend and the workers."
  value       = aws_lb.internal.dns_name
}

output "internal_alb_arn_suffix" {
  description = "ARN suffix of the internal load balancer, for request-count scaling of the OPA group."
  value       = aws_lb.internal.arn_suffix
}

output "public_target_group_arns" {
  description = "Target group ARN for each publicly routed service, keyed by role."
  value       = { for role, group in aws_lb_target_group.public : role => group.arn }
}

output "public_target_group_arn_suffixes" {
  description = "Target group ARN suffix for each publicly routed service, keyed by role."
  value       = { for role, group in aws_lb_target_group.public : role => group.arn_suffix }
}

output "internal_target_group_arn" {
  description = "Target group ARN the OPA Auto Scaling group registers with."
  value       = aws_lb_target_group.internal.arn
}

output "internal_target_group_arn_suffix" {
  description = "Target group ARN suffix for the OPA group's request-count scaling policy."
  value       = aws_lb_target_group.internal.arn_suffix
}

output "certificate_arn" {
  description = "ARN of the validated ACM certificate served by the HTTPS listener."
  value       = aws_acm_certificate_validation.this.certificate_arn
}
