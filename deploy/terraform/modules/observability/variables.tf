variable "name_prefix" {
  description = "Prefix applied to every resource name, e.g. greensecops-production."
  type        = string
}

variable "alarm_email" {
  description = "Address subscribed to the alarm topic. Leave empty to create the topic without a subscription and wire up notifications separately."
  type        = string
  default     = ""
}

variable "autoscaling_group_names" {
  description = "Auto Scaling group name for each service, keyed by role. Each gets a sustained-CPU alarm."
  type        = map(string)
}

variable "public_alb_arn_suffix" {
  description = "ARN suffix of the internet-facing load balancer, for its error-rate and health alarms."
  type        = string
}

variable "public_target_group_arn_suffixes" {
  description = "Target group ARN suffix for each publicly routed service, keyed by role. Each gets an unhealthy-host alarm."
  type        = map(string)
}

variable "postgres_instance_id" {
  description = "RDS instance identifier the database alarms are scoped to."
  type        = string
}

variable "redis_replication_group_id" {
  description = "ElastiCache replication group ID the cache alarms are scoped to."
  type        = string
}

variable "postgres_storage_alarm_bytes" {
  description = "Free-storage floor, in bytes, below which the database storage alarm fires."
  type        = number
  default     = 10737418240 # 10 GiB
}

variable "kms_key_arn" {
  description = "Customer-managed KMS key encrypting the alarm topic."
  type        = string
}

variable "tags" {
  description = "Tags applied to every resource in this module."
  type        = map(string)
}
