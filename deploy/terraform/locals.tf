data "aws_availability_zones" "available" {
  state = "available"
}

# Amazon Linux 2023 is the baseline: SSM agent preinstalled (Ansible's only way
# in), and a current Docker package in the default repositories.
data "aws_ssm_parameter" "al2023_ami" {
  name = "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-${var.instance_architecture}"
}

locals {
  name_prefix = "${var.project}-${var.environment}"

  common_tags = merge(var.tags, {
    Project     = var.project
    Environment = var.environment
    ManagedBy   = "terraform"
    Repository  = "greensecops"
  })

  availability_zones = slice(
    data.aws_availability_zones.available.names,
    0,
    var.availability_zone_count,
  )

  ami_id = data.aws_ssm_parameter.al2023_ami.value

  # ----------------------------------------------------------------------
  # Service topology
  # ----------------------------------------------------------------------
  # The seven containers compose.yml runs on one host, each on its own group.
  # `exposure` decides which load balancer (if any) fronts the role; `port` is
  # the container port; the Celery roles accept no inbound traffic at all.

  service_topology = {
    backend = {
      port              = 8000
      exposure          = "public"
      health_check_path = "/api/v1/utils/health-check/"
      priority          = 10
    }
    frontend = {
      port              = 8080
      exposure          = "public"
      health_check_path = "/"
      priority          = 20
    }
    landing = {
      port              = 8080
      exposure          = "public"
      health_check_path = "/"
      priority          = 30
    }
    docs = {
      port              = 8080
      exposure          = "public"
      health_check_path = "/"
      priority          = 40
    }
    opa = {
      port              = 8181
      exposure          = "internal"
      health_check_path = "/health"
      priority          = null
    }
    celery-worker = {
      port              = null
      exposure          = "none"
      health_check_path = null
      priority          = null
    }
    celery-beat = {
      port              = null
      exposure          = "none"
      health_check_path = null
      priority          = null
    }
  }

  public_roles = [for role, svc in local.service_topology : role if svc.exposure == "public"]

  # Roles running the application code that opens database, cache and policy
  # connections. The three static-content roles do not.
  data_client_roles = ["backend", "celery-worker", "celery-beat"]

  # ----------------------------------------------------------------------
  # Hostnames and URLs
  # ----------------------------------------------------------------------

  hostnames = {
    backend  = "${var.api_subdomain}.${var.domain_name}"
    frontend = "${var.app_subdomain}.${var.domain_name}"
    docs     = "${var.docs_subdomain}.${var.domain_name}"
    landing  = var.domain_name
  }

  urls = { for role, host in local.hostnames : role => "https://${host}" }

  # ----------------------------------------------------------------------
  # Parameter Store layout
  # ----------------------------------------------------------------------
  # /config/* is written by Terraform and readable by every role.
  # /secret/* is declared here with placeholder values and seeded out of band,
  # readable only by the roles that run application code.

  ssm_prefix = "/${var.project}/${var.environment}"
}
