# --------------------------------------------------------------------------
# Identity
# --------------------------------------------------------------------------

variable "project" {
  description = "Project slug used as the prefix for every resource name."
  type        = string
  default     = "greensecops"
}

variable "environment" {
  description = "Environment this root manages. Also passed to the backend as ENVIRONMENT, where anything other than \"local\" makes the placeholder-secret guard in app/core/config.py fatal."
  type        = string

  validation {
    condition     = contains(["staging", "production"], var.environment)
    error_message = "environment must be either staging or production."
  }
}

variable "aws_region" {
  description = "AWS region the whole environment is deployed into."
  type        = string
}

variable "tags" {
  description = "Extra tags merged into every resource on top of the built-in Project/Environment/ManagedBy set."
  type        = map(string)
  default     = {}
}

# --------------------------------------------------------------------------
# Network
# --------------------------------------------------------------------------

variable "vpc_cidr" {
  description = "IPv4 CIDR block for the VPC. A /16 gives each of the three tiers a /20 per availability zone."
  type        = string
  default     = "10.30.0.0/16"
}

variable "availability_zone_count" {
  description = "Number of availability zones to spread the subnets across. Two is the minimum for a Multi-AZ database."
  type        = number
  default     = 3

  validation {
    condition     = var.availability_zone_count >= 2 && var.availability_zone_count <= 4
    error_message = "availability_zone_count must be between 2 and 4."
  }
}

variable "single_nat_gateway" {
  description = "Route every private subnet through one NAT gateway instead of one per AZ. Saves roughly the cost of a small instance per AZ; acceptable for staging, not for production."
  type        = bool
  default     = false
}

variable "public_ingress_cidrs" {
  description = "CIDR blocks allowed to reach the load balancer on 80/443. The default is the whole internet because the dashboard, API, docs and landing page are public by design."
  type        = list(string)
  default     = ["0.0.0.0/0"]
}

# --------------------------------------------------------------------------
# DNS and certificates
# --------------------------------------------------------------------------

variable "route53_zone_id" {
  description = "Hosted zone ID for domain_name. The zone must already exist and be delegated; this config creates records in it but does not own it."
  type        = string
}

variable "domain_name" {
  description = "Apex domain serving the landing page, e.g. greensecops.example.com."
  type        = string
}

variable "app_subdomain" {
  description = "Subdomain label for the frontend dashboard. Becomes FRONTEND_HOST and the GitHub OAuth callback's host."
  type        = string
  default     = "app"
}

variable "api_subdomain" {
  description = "Subdomain label for the backend API. Becomes BACKEND_HOST and the GitHub App's webhook host."
  type        = string
  default     = "api"
}

variable "docs_subdomain" {
  description = "Subdomain label for the Sphinx documentation site. Becomes DOCS_URL."
  type        = string
  default     = "docs"
}

# --------------------------------------------------------------------------
# Images
# --------------------------------------------------------------------------

variable "ecr_registry" {
  description = "ECR registry hostname images are pulled from, as output by the bootstrap root (<account>.dkr.ecr.<region>.amazonaws.com)."
  type        = string
}

variable "ecr_repository_arns" {
  description = "ARNs of the ECR repositories, as output by the bootstrap root. Used to scope the instance roles' pull permission."
  type        = list(string)
}

variable "image_tag" {
  description = "Container image tag every service runs. Ansible reads this from Parameter Store, so a rollback is a tfvars change plus a deploy, not a rebuild."
  type        = string
  default     = "latest"
}

variable "instance_architecture" {
  description = "CPU architecture for the instance AMI. arm64 (Graviton) is the default and matches the multi-arch OPA image pinned in opa/Dockerfile."
  type        = string
  default     = "arm64"

  validation {
    condition     = contains(["arm64", "x86_64"], var.instance_architecture)
    error_message = "instance_architecture must be either arm64 or x86_64."
  }
}

# --------------------------------------------------------------------------
# Service sizing
# --------------------------------------------------------------------------

variable "services" {
  description = "Per-role instance sizing. `min`/`max` bound the Auto Scaling group and `desired` seeds it; roles whose min equals max are pinned. Keys must match the role set in locals.tf."
  type = map(object({
    instance_type = string
    min           = number
    max           = number
    desired       = number
  }))

  default = {
    backend       = { instance_type = "t4g.medium", min = 2, max = 2, desired = 2 }
    frontend      = { instance_type = "t4g.small", min = 2, max = 2, desired = 2 }
    landing       = { instance_type = "t4g.small", min = 1, max = 1, desired = 1 }
    docs          = { instance_type = "t4g.small", min = 1, max = 1, desired = 1 }
    celery-worker = { instance_type = "t4g.medium", min = 2, max = 10, desired = 2 }
    celery-beat   = { instance_type = "t4g.small", min = 1, max = 1, desired = 1 }
    opa           = { instance_type = "t4g.small", min = 2, max = 6, desired = 2 }
  }
}

variable "celery_worker_target_cpu" {
  description = "Average CPU across the Celery worker group the target-tracking policy holds. Analysis tasks are CPU-bound, so this is the scaling signal."
  type        = number
  default     = 60
}

variable "opa_target_requests_per_instance" {
  description = "Requests per OPA instance per minute the target-tracking policy holds. Policy evaluation is request-bound rather than CPU-bound."
  type        = number
  default     = 600
}

variable "celery_concurrency" {
  description = "Worker processes per Celery instance, passed through as CELERY_CONCURRENCY. Multiply by the group size for total parallelism."
  type        = number
  default     = 4
}

# --------------------------------------------------------------------------
# Data tier
# --------------------------------------------------------------------------

variable "postgres_instance_class" {
  description = "RDS instance class. Graviton (db.m7g/db.t4g) matches the arm64 application instances."
  type        = string
  default     = "db.t4g.medium"
}

variable "postgres_allocated_storage" {
  description = "Initial database storage, in GiB."
  type        = number
  default     = 50
}

variable "postgres_multi_az" {
  description = "Run a synchronous standby in a second availability zone. Doubles the database cost."
  type        = bool
  default     = true
}

variable "postgres_backup_retention_days" {
  description = "Days of automated database backups to retain."
  type        = number
  default     = 14
}

variable "postgres_deletion_protection" {
  description = "Refuse to destroy the database until this is turned off."
  type        = bool
  default     = true
}

variable "redis_node_type" {
  description = "ElastiCache node type for the Celery broker and token cache."
  type        = string
  default     = "cache.t4g.small"
}

variable "redis_replica_count" {
  description = "Read replicas in the Redis replication group. 1 or more enables automatic failover."
  type        = number
  default     = 1
}

variable "artifact_bucket_name" {
  description = "Globally unique bucket name for large scan artifacts. Becomes S3_BUCKET."
  type        = string
}

variable "artifact_retention_days" {
  description = "Days before a scan artifact is expired. Artifacts are regenerable, so this is a cost control."
  type        = number
  default     = 90
}

variable "artifact_bucket_force_destroy" {
  description = "Allow `terraform destroy` to delete a non-empty artifact bucket. Useful for staging, dangerous in production."
  type        = bool
  default     = false
}

variable "access_log_bucket_name" {
  description = "Globally unique bucket name for load-balancer access logs."
  type        = string
}

variable "ansible_transfer_bucket_name" {
  description = "Globally unique bucket name Ansible's aws_ssm connection plugin stages files through. Contents are transient and expire after a day."
  type        = string
}

# --------------------------------------------------------------------------
# Operations
# --------------------------------------------------------------------------

variable "log_retention_days" {
  description = "Retention, in days, for every CloudWatch log group this config creates."
  type        = number
  default     = 30
}

variable "alarm_email" {
  description = "Address subscribed to the alarm topic. Leave empty to create the topic without a subscription."
  type        = string
  default     = ""
}

variable "deletion_protection" {
  description = "Refuse to destroy the load balancers until this is turned off."
  type        = bool
  default     = true
}
