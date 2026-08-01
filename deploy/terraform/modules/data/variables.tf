variable "name_prefix" {
  description = "Prefix applied to every resource name, e.g. greensecops-production."
  type        = string
}

variable "create_managed_database" {
  description = "Create an RDS instance. False in the single_host topology, where PostgreSQL runs as a container on the application host's persistent volume."
  type        = bool
  default     = true
}

variable "create_managed_cache" {
  description = "Create an ElastiCache replication group. False in the single_host topology, where Redis runs as a container."
  type        = bool
  default     = true
}

variable "subnet_ids" {
  description = "Isolated subnet IDs the database and cache are placed in."
  type        = list(string)
}

variable "postgres_security_group_id" {
  description = "Security group attached to the RDS instance."
  type        = string
}

variable "redis_security_group_id" {
  description = "Security group attached to the ElastiCache replication group."
  type        = string
}

variable "kms_key_arn" {
  description = "Customer-managed KMS key encrypting the database, the cache and the artifact bucket."
  type        = string
}

variable "database_name" {
  description = "Name of the application database created on the instance. Must match POSTGRES_DB in the backend settings."
  type        = string
  default     = "greensecops"
}

variable "database_username" {
  description = "Master username for the PostgreSQL instance."
  type        = string
  default     = "greensecops"
}

variable "postgres_version" {
  description = "PostgreSQL major version. The application is developed against 18, matching compose.yml."
  type        = string
  default     = "18"
}

variable "postgres_instance_class" {
  description = "RDS instance class. Graviton (db.m7g/db.t4g) matches the arm64 application instances."
  type        = string
}

variable "postgres_allocated_storage" {
  description = "Initial storage, in GiB, for the RDS instance."
  type        = number
  default     = 50
}

variable "postgres_max_allocated_storage" {
  description = "Upper bound, in GiB, for RDS storage autoscaling. Set equal to postgres_allocated_storage to disable it."
  type        = number
  default     = 500
}

variable "postgres_multi_az" {
  description = "Run a synchronous standby in a second availability zone. Doubles the instance cost; required for any meaningful availability target."
  type        = bool
}

variable "postgres_backup_retention_days" {
  description = "Days of automated backups to retain. Point-in-time recovery covers this window."
  type        = number
  default     = 14
}

variable "postgres_deletion_protection" {
  description = "Refuse to destroy the database until this is turned off. Leave enabled in production."
  type        = bool
}

variable "redis_node_type" {
  description = "ElastiCache node type, e.g. cache.t4g.small."
  type        = string
}

variable "redis_version" {
  description = "Redis engine version. The application is developed against 8, matching compose.yml."
  type        = string
  default     = "8.0"
}

variable "redis_replica_count" {
  description = "Number of read replicas in the replication group. 1 or more enables automatic failover."
  type        = number
  default     = 1
}

variable "artifact_bucket_name" {
  description = "Globally unique name for the bucket holding large scan artifacts (Terraform bundles, cloud snapshots)."
  type        = string
}

variable "artifact_retention_days" {
  description = "Days before a scan artifact is expired. Artifacts are regenerable, so this is a cost control rather than a retention policy."
  type        = number
  default     = 90
}

variable "artifact_bucket_force_destroy" {
  description = "Allow `terraform destroy` to delete a non-empty artifact bucket. Useful for staging, dangerous in production."
  type        = bool
  default     = false
}

variable "log_retention_days" {
  description = "Retention, in days, for the exported PostgreSQL log groups."
  type        = number
  default     = 30
}

variable "tags" {
  description = "Tags applied to every resource in this module."
  type        = map(string)
}

variable "ansible_transfer_bucket_name" {
  description = "Globally unique bucket name used by Ansible's aws_ssm connection plugin to move files onto the instances. Contents are transient — the lifecycle rule expires them after a day."
  type        = string
}
