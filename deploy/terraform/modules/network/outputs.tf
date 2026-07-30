output "vpc_id" {
  description = "ID of the VPC every other module attaches to."
  value       = aws_vpc.this.id
}

output "vpc_cidr" {
  description = "CIDR block of the VPC, used to scope intra-VPC security-group rules."
  value       = aws_vpc.this.cidr_block
}

output "public_subnet_ids" {
  description = "Public subnet IDs, for the internet-facing load balancer."
  value       = aws_subnet.public[*].id
}

output "private_subnet_ids" {
  description = "Private subnet IDs, for the application Auto Scaling groups."
  value       = aws_subnet.private[*].id
}

output "isolated_subnet_ids" {
  description = "Isolated subnet IDs, for RDS and ElastiCache."
  value       = aws_subnet.isolated[*].id
}
