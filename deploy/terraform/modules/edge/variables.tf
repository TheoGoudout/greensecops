variable "name_prefix" {
  description = "Prefix applied to every resource name, e.g. greensecops-production."
  type        = string
}

variable "vpc_id" {
  description = "VPC the target groups resolve targets in."
  type        = string
}

variable "public_subnet_ids" {
  description = "Public subnets the internet-facing load balancer is placed in."
  type        = list(string)
}

variable "private_subnet_ids" {
  description = "Private subnets the internal load balancer is placed in."
  type        = list(string)
}

variable "public_alb_security_group_id" {
  description = "Security group for the internet-facing load balancer."
  type        = string
}

variable "internal_alb_security_group_id" {
  description = "Security group for the internal load balancer. Empty when the topology has none."
  type        = string
  default     = ""
}

variable "route53_zone_id" {
  description = "Hosted zone the public records and the ACM validation records are created in."
  type        = string
}

variable "domain_name" {
  description = "Apex domain serving the landing page, e.g. greensecops.example.com."
  type        = string
}

variable "hostnames" {
  description = "Fully-qualified hostname for each publicly routed service, keyed by role. The apex domain is included as the landing page's hostname."
  type        = map(string)
}

variable "public_services" {
  description = "Services routed by the internet-facing load balancer, keyed by service name. `port` is the *host* port the container publishes — which differs from the container port when several services share a box and cannot all take :80. `priority` orders the host-based listener rules."
  type = map(object({
    port              = number
    health_check_path = string
    priority          = number
  }))
}

variable "internal_service" {
  description = "The service behind the internal load balancer (OPA), with the port and health-check path to probe. Null when the topology has no internal load balancer because OPA shares a host with the backend."
  type = object({
    port              = number
    health_check_path = string
  })
  default = null
}

variable "access_log_bucket_name" {
  description = "Globally unique name for the bucket receiving load-balancer access logs."
  type        = string
}

variable "access_log_retention_days" {
  description = "Days before an access-log object is expired."
  type        = number
  default     = 90
}

variable "deletion_protection" {
  description = "Refuse to destroy the load balancers until this is turned off. Leave enabled in production."
  type        = bool
}

variable "ssl_policy" {
  description = "ELB security policy for the HTTPS listener. The TLS13 policies drop everything below TLS 1.2."
  type        = string
  default     = "ELBSecurityPolicy-TLS13-1-2-2021-06"
}

variable "tags" {
  description = "Tags applied to every resource in this module."
  type        = map(string)
}
