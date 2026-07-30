output "public_alb_security_group_id" {
  description = "Security group of the internet-facing load balancer."
  value       = aws_security_group.public_alb.id
}

output "internal_alb_security_group_id" {
  description = "Security group of the internal load balancer fronting OPA."
  value       = aws_security_group.internal_alb.id
}

output "service_security_group_ids" {
  description = "Security group ID of each application role, keyed by role."
  value       = { for role, sg in aws_security_group.service : role => sg.id }
}

output "postgres_security_group_id" {
  description = "Security group to attach to the RDS instance."
  value       = aws_security_group.postgres.id
}

output "redis_security_group_id" {
  description = "Security group to attach to the ElastiCache replication group."
  value       = aws_security_group.redis.id
}
