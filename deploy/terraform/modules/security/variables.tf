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

variable "groups" {
  description = "Every host group, keyed by group name. `public_ports` are reached from the internet-facing load balancer and `internal_ports` from the internal one; a group running only Celery has neither. A group is whatever set of containers shares a box — one per service in the distributed topology, one in total in single_host."
  type = map(object({
    public_ports   = list(number)
    internal_ports = list(number)
  }))
}

variable "data_client_groups" {
  description = "Groups running a container that opens a PostgreSQL or Redis connection. Everything else is denied at the security-group level."
  type        = list(string)
}

variable "managed_database" {
  description = "Whether an RDS instance exists to guard. False when PostgreSQL runs as a container on the application host, where the Docker network is the only path to it."
  type        = bool
}

variable "managed_cache" {
  description = "Whether an ElastiCache replication group exists to guard."
  type        = bool
}

variable "internal_load_balancer" {
  description = "Whether an internal load balancer exists to guard. False when OPA shares a host with the backend and is reached over the Docker network instead."
  type        = bool
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
