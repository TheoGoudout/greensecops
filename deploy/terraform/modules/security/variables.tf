variable "name_prefix" {
  description = "Prefix applied to every security-group name, e.g. greensecops-production."
  type        = string
}

variable "vpc_id" {
  description = "VPC the security groups belong to."
  type        = string
}

variable "vpc_cidr" {
  description = "CIDR block of the VPC, used to scope the load balancers' egress to their targets."
  type        = string
}

variable "services" {
  description = "Every deployed service, keyed by role. `port` is the container port the service listens on (null for the Celery roles, which accept no inbound traffic); `exposure` is \"public\" behind the internet-facing load balancer, \"internal\" behind the internal one, or \"none\"."
  type = map(object({
    port     = optional(number)
    exposure = string
  }))

  validation {
    condition     = alltrue([for svc in var.services : contains(["public", "internal", "none"], svc.exposure)])
    error_message = "Each service's exposure must be one of: public, internal, none."
  }

  validation {
    condition     = alltrue([for svc in var.services : svc.port != null if svc.exposure != "none"])
    error_message = "A service with exposure \"public\" or \"internal\" must declare a port."
  }
}

variable "data_client_roles" {
  description = "Roles allowed to open connections to PostgreSQL, Redis and the internal OPA load balancer. Everything else is denied at the security-group level."
  type        = list(string)
}

variable "public_ingress_cidrs" {
  description = "CIDR blocks allowed to reach the internet-facing load balancer on 80/443. Defaults to the whole internet because the dashboard, API, docs and landing page are public by design; narrow it to reach a private deployment."
  type        = list(string)
  default     = ["0.0.0.0/0"]
}

variable "postgres_port" {
  description = "Port the RDS PostgreSQL instance listens on."
  type        = number
  default     = 5432
}

variable "redis_port" {
  description = "Port the ElastiCache Redis replication group listens on."
  type        = number
  default     = 6379
}

variable "tags" {
  description = "Tags applied to every resource in this module."
  type        = map(string)
}
