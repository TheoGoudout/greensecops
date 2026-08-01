variable "name_prefix" {
  description = "Prefix applied to every resource name, e.g. greensecops-production."
  type        = string
}

variable "role" {
  description = "Service role this instance group runs, e.g. backend or celery-worker. Becomes the greensecops:role tag Ansible's dynamic inventory groups on."
  type        = string
}

variable "services" {
  description = "Container names this group runs. Written to the instance and to a tag so Ansible renders a compose file with exactly these services, without re-deriving the topology."
  type        = list(string)
}

variable "ami_id" {
  description = "AMI the instances boot from."
  type        = string
}

variable "instance_type" {
  description = "EC2 instance type. Must match the AMI's architecture."
  type        = string
}

variable "instance_profile_name" {
  description = "IAM instance profile granting this role its AWS permissions."
  type        = string
}

variable "subnet_ids" {
  description = "Private subnets the instances are spread across."
  type        = list(string)
}

variable "security_group_ids" {
  description = "Security groups attached to the instances."
  type        = list(string)
}

variable "assign_public_ip" {
  description = "Give each instance a public address. Required when the group runs in public subnets because there is no NAT gateway to reach the internet through; inbound remains closed by the security group."
  type        = bool
  default     = false
}

variable "user_data" {
  description = "Cloud-init script run on first boot. Kept minimal — Ansible does the real configuration."
  type        = string
}

variable "min_size" {
  description = "Minimum number of instances in the group."
  type        = number
}

variable "max_size" {
  description = "Maximum number of instances in the group. Equal to min_size pins the group to a fixed size."
  type        = number
}

variable "desired_capacity" {
  description = "Instance count to start from. Ignored on subsequent applies when autoscaling is enabled, so a scaling event is not reverted by the next terraform apply."
  type        = number
}

variable "target_group_arns" {
  description = "Load-balancer target groups to register instances with. Empty for services that accept no inbound traffic."
  type        = list(string)
  default     = []
}

variable "autoscaling" {
  description = "Target-tracking policy for load-driven roles. `metric` is either \"cpu\" (average CPU across the group) or \"requests\" (requests per target, which needs a target group and both ARN suffixes below). Null pins the group to a fixed size."
  type = object({
    metric       = string
    target_value = number
  })
  default = null

  validation {
    condition     = var.autoscaling == null || contains(["cpu", "requests"], try(var.autoscaling.metric, ""))
    error_message = "autoscaling.metric must be either \"cpu\" or \"requests\"."
  }
}

variable "alb_arn_suffix" {
  description = "ARN suffix of the load balancer fronting this service, as `aws_lb.arn_suffix`. Required only when autoscaling on the \"requests\" metric."
  type        = string
  default     = ""
}

variable "target_group_arn_suffix" {
  description = "ARN suffix of this service's target group, as `aws_lb_target_group.arn_suffix`. Required only when autoscaling on the \"requests\" metric."
  type        = string
  default     = ""
}

variable "root_volume_size" {
  description = "Size, in GiB, of the encrypted root volume. Container images and layer cache live here."
  type        = number
  default     = 30
}

variable "kms_key_arn" {
  description = "Customer-managed KMS key encrypting the root volume and the log group."
  type        = string
}

variable "log_retention_days" {
  description = "Retention, in days, for this service's CloudWatch log group."
  type        = number
  default     = 30
}

variable "health_check_grace_period" {
  description = "Seconds to wait after an instance launches before its load-balancer health counts. Must cover cloud-init plus the Ansible-driven container start."
  type        = number
  default     = 600
}

variable "tags" {
  description = "Tags applied to every resource in this module."
  type        = map(string)
}
