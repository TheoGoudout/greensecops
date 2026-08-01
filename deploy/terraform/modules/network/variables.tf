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

variable "nat_gateway_count" {
  description = "NAT gateways to create, from 0 to one per availability zone. Fewer than the AZ count makes the surviving gateways' AZs a single point of failure for egress; 0 means the private subnets have no route out at all, which is only viable when the instances sit in the public subnets instead."
  type        = number

  validation {
    condition     = var.nat_gateway_count >= 0
    error_message = "nat_gateway_count cannot be negative."
  }
}

variable "interface_endpoints" {
  description = "AWS service names to reach over PrivateLink instead of the internet, e.g. [\"ssm\", \"ecr.api\"]. Each is billed per availability zone — roughly $8/month each — so an empty list is the right default until the NAT data-processing charge they displace exceeds that."
  type        = list(string)
  default     = []
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
