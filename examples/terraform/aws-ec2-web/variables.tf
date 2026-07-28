variable "region" {
  description = "AWS region the web tier is deployed into."
  type        = string
  default     = "us-east-1"
}

variable "name" {
  description = "Name prefix for the web-tier resources."
  type        = string
}

variable "vpc_id" {
  description = "ID of the VPC the security group belongs to."
  type        = string
}

variable "ami_id" {
  description = "AMI used for the web instance."
  type        = string
}

variable "availability_zone" {
  description = "Availability zone for the instance and its data volume."
  type        = string
  default     = "us-east-1a"
}
