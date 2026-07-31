# Every database and cache output is empty in the single_host topology, where
# both run as containers on the application host. The root module substitutes
# in-container addresses in that case — see the config parameters in ssm.tf.

output "postgres_address" {
  description = "Hostname of the RDS instance, for POSTGRES_SERVER. Empty when PostgreSQL runs as a container."
  value       = try(aws_db_instance.this[0].address, "")
}

output "postgres_port" {
  description = "Port of the RDS instance, for POSTGRES_PORT. Empty when PostgreSQL runs as a container."
  value       = try(tostring(aws_db_instance.this[0].port), "")
}

output "postgres_database_name" {
  description = "Application database name, for POSTGRES_DB."
  value       = try(aws_db_instance.this[0].db_name, var.database_name)
}

output "postgres_username" {
  description = "Master username, for POSTGRES_USER."
  value       = try(aws_db_instance.this[0].username, var.database_username)
}

output "postgres_master_secret_arn" {
  description = "ARN of the RDS-managed Secrets Manager secret holding the master password. Empty when PostgreSQL runs as a container, where the password is an ordinary SecureString parameter instead."
  value       = try(aws_db_instance.this[0].master_user_secret[0].secret_arn, "")
}

output "redis_url" {
  description = "Connection URL for the Celery broker and cache, for REDIS_URL. Uses rediss:// because transit encryption is enforced. Empty when Redis runs as a container."
  value       = try("rediss://${aws_elasticache_replication_group.this[0].primary_endpoint_address}:${aws_elasticache_replication_group.this[0].port}/0?ssl_cert_reqs=required", "")
}

output "artifact_bucket_name" {
  description = "Object-storage bucket for scan artifacts, for S3_BUCKET. Real S3 in every topology — it is a few dollars a month and means artifacts outlive the host."
  value       = aws_s3_bucket.artifacts.id
}

output "artifact_bucket_arn" {
  description = "ARN of the artifact bucket, used to scope the instance policies."
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
