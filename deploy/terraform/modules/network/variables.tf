variable "name_prefix" {
  description = "Prefix applied to every resource name, e.g. greensecops-production."
  type        = string
}

variable "vpc_cidr" {
  description = "IPv4 CIDR block for the VPC. Must be large enough for three /20 tiers across every AZ."
  type        = string
}

variable "availability_zones" {
  description = "Availability zones to spread the subnets across, in order."
  type        = list(string)
}

variable "single_nat_gateway" {
  description = "Route every private subnet through one NAT gateway instead of one per AZ. Cheaper, but the NAT's AZ becomes a single point of failure for egress."
  type        = bool
  default     = false
}

variable "flow_log_retention_days" {
  description = "Retention, in days, for the VPC flow-log group."
  type        = number
  default     = 30
}

variable "tags" {
  description = "Tags applied to every resource in this module."
  type        = map(string)
}
