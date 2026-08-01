variable "name_prefix" {
  description = "Prefix applied to every resource name, e.g. greensecops-production."
  type        = string
}

variable "availability_zone" {
  description = "Availability zone the volume lives in. An EBS volume cannot cross zones, so this pins the host group that mounts it to the same zone — the reason the single_host topology has no redundancy."
  type        = string
}

variable "size" {
  description = "Size, in GiB, of the volume holding PostgreSQL, Redis and object data."
  type        = number
}

variable "snapshot_retention" {
  description = "Daily snapshots to retain. In the single_host topology this is the only backup of the database."
  type        = number
}

variable "snapshot_hour_utc" {
  description = "Hour, in UTC, at which the daily snapshot is taken. Pick a quiet one — the snapshot is crash-consistent, not application-consistent."
  type        = string
  default     = "03:00"
}

variable "kms_key_arn" {
  description = "Customer-managed KMS key encrypting the volume and its snapshots."
  type        = string
}

variable "tags" {
  description = "Tags applied to every resource in this module."
  type        = map(string)
}
