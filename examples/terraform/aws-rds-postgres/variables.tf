variable "region" {
  description = "AWS region for the database."
  type        = string
  default     = "us-east-1"
}

variable "name" {
  description = "Name prefix for the database resources."
  type        = string
}

# A plumbing variable that slipped through code review without a description —
# exactly the kind of omission the variable_missing_description rule catches.
variable "subnet_ids" {
  type = list(string)
}

variable "db_password" {
  description = "Master password for the Postgres instance."
  type        = string
  sensitive   = true
}
