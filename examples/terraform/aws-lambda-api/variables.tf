variable "project" {
  description = "Name prefix for every resource in this module."
  type        = string
}

variable "region" {
  description = "AWS region to deploy into."
  type        = string
  default     = "eu-west-1"
}

variable "environment" {
  description = "Environment name, used for tagging."
  type        = string
  default     = "prod"
}

variable "db_username" {
  description = "Master username for the PostgreSQL instance."
  type        = string
}

variable "db_password" {
  description = "Master password for the PostgreSQL instance, supplied from a secret store."
  type        = string
  sensitive   = true
}
