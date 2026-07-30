output "postgres_address" {
  description = "Hostname of the RDS instance, for POSTGRES_SERVER."
  value       = aws_db_instance.this.address
}

output "postgres_port" {
  description = "Port of the RDS instance, for POSTGRES_PORT."
  value       = aws_db_instance.this.port
}

output "postgres_database_name" {
  description = "Application database name, for POSTGRES_DB."
  value       = aws_db_instance.this.db_name
}

output "postgres_username" {
  description = "Master username, for POSTGRES_USER."
  value       = aws_db_instance.this.username
}

output "postgres_master_secret_arn" {
  description = "ARN of the RDS-managed Secrets Manager secret holding the master password. Ansible reads it on the instance to build the DSN; it is never written to Terraform state."
  value       = aws_db_instance.this.master_user_secret[0].secret_arn
}

output "redis_url" {
  description = "Connection URL for the Celery broker and cache, for REDIS_URL. Uses rediss:// because transit encryption is enforced."
  value       = "rediss://${aws_elasticache_replication_group.this.primary_endpoint_address}:${aws_elasticache_replication_group.this.port}/0?ssl_cert_reqs=required"
}

output "artifact_bucket_name" {
  description = "Object-storage bucket for scan artifacts, for S3_BUCKET."
  value       = aws_s3_bucket.artifacts.id
}

output "artifact_bucket_arn" {
  description = "ARN of the artifact bucket, used to scope the backend and worker instance policies."
  value       = aws_s3_bucket.artifacts.arn
}

output "ansible_transfer_bucket_name" {
  description = "Bucket Ansible's aws_ssm connection plugin stages files through."
  value       = aws_s3_bucket.ansible_transfer.id
}

output "ansible_transfer_bucket_arn" {
  description = "ARN of the Ansible transfer bucket, used to scope every instance role's scratch access."
  value       = aws_s3_bucket.ansible_transfer.arn
}
