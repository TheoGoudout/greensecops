variable "project" {
  description = "Name prefix for every resource in this module."
  type        = string
}

variable "region" {
  description = "AWS region to deploy the cluster into."
  type        = string
  default     = "eu-west-1"
}

variable "environment" {
  description = "Environment name, used for tagging."
  type        = string
  default     = "prod"
}

variable "subnet_ids" {
  description = "Subnets the cluster's control plane ENIs are placed in."
}
