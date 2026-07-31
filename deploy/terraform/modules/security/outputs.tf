output "public_alb_security_group_id" {
  description = "Security group of the internet-facing load balancer."
  value       = aws_security_group.public_alb.id
}

output "internal_alb_security_group_id" {
  description = "Security group of the internal load balancer, or an empty string when the topology has none."
  value       = try(aws_security_group.internal_alb[0].id, "")
}

output "group_security_group_ids" {
  description = "Security group ID of each host group, keyed by group name."
  value       = { for group, sg in aws_security_group.group : group => sg.id }
}

output "postgres_security_group_id" {
  description = "Security group to attach to the RDS instance, or an empty string when PostgreSQL runs as a container."
  value       = try(aws_security_group.postgres[0].id, "")
}

output "redis_security_group_id" {
  description = "Security group to attach to the ElastiCache replication group, or an empty string when Redis runs as a container."
  value       = try(aws_security_group.redis[0].id, "")
}
