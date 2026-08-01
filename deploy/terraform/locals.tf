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
    Topology    = var.topology
  })

  availability_zones = slice(
    data.aws_availability_zones.available.names,
    0,
    var.availability_zone_count,
  )

  ami_id = data.aws_ssm_parameter.al2023_ami.value

  # ----------------------------------------------------------------------
  # Services
  # ----------------------------------------------------------------------
  # What each container is, independent of where it runs. `container_port` is
  # what the process listens on inside the container; `host_port` is what it is
  # published as. The two differ for the static sites because co-locating them
  # on one host means three nginx containers cannot all take :80 — the load
  # balancer's target group uses host_port, so a host-header rule reaches the
  # right container whether it has the box to itself or shares it.

  service_topology = {
    backend = {
      container_port    = 8000
      host_port         = 8000
      exposure          = "public"
      health_check_path = "/api/v1/utils/health-check/"
      priority          = 10
      needs_app_env     = true
    }
    frontend = {
      container_port    = 80
      host_port         = 8081
      exposure          = "public"
      health_check_path = "/"
      priority          = 20
      needs_app_env     = false
    }
    landing = {
      container_port    = 80
      host_port         = 8082
      exposure          = "public"
      health_check_path = "/"
      priority          = 30
      needs_app_env     = false
    }
    docs = {
      container_port    = 80
      host_port         = 8083
      exposure          = "public"
      health_check_path = "/"
      priority          = 40
      needs_app_env     = false
    }
    opa = {
      container_port    = 8181
      host_port         = 8181
      exposure          = "internal"
      health_check_path = "/health"
      priority          = null
      needs_app_env     = false
    }
    celery-worker = {
      container_port    = null
      host_port         = null
      exposure          = "none"
      health_check_path = null
      priority          = null
      needs_app_env     = true
    }
    celery-beat = {
      container_port    = null
      host_port         = null
      exposure          = "none"
      health_check_path = null
      priority          = null
      needs_app_env     = true
    }
  }

  public_services   = { for name, svc in local.service_topology : name => svc if svc.exposure == "public" }
  internal_services = { for name, svc in local.service_topology : name => svc if svc.exposure == "internal" }

  # Services whose container opens a database, cache or policy connection.
  data_client_services = ["backend", "celery-worker", "celery-beat"]

  # ----------------------------------------------------------------------
  # Topology
  # ----------------------------------------------------------------------
  # Three shapes of the same deployment, differing only in how many hosts the
  # services are spread across and how much of the data tier is managed. Moving
  # between them is a variable change, not a rewrite — see the migration
  # section of deploy/README.md for what should trigger each step.
  #
  #   single_host   every container on one box, exactly like compose.yml.
  #                 PostgreSQL, Redis and object storage run as containers on a
  #                 persistent volume. No NAT, no interface endpoints, no
  #                 internal load balancer. Cheapest by a wide margin, and no
  #                 redundancy at all — one instance, one availability zone.
  #
  #   consolidated  three groups: static sites, API + policy, workers. Managed
  #                 PostgreSQL and Redis. One NAT gateway. Survives an instance
  #                 failure in every tier; still one NAT and one database.
  #
  #   distributed   one group per service, everything managed and multi-AZ.
  #                 What the workload needs once any single tier outgrows a box.

  topology_presets = {
    single_host = {
      groups = {
        app = ["backend", "frontend", "landing", "docs", "opa", "celery-worker", "celery-beat"]
      }
      managed_database       = false
      managed_cache          = false
      nat_gateway_count      = 0
      interface_endpoints    = []
      internal_load_balancer = false
      instances_are_public   = true
      persistent_volume      = true
    }

    consolidated = {
      groups = {
        web    = ["frontend", "landing", "docs"]
        app    = ["backend", "opa"]
        worker = ["celery-worker", "celery-beat"]
      }
      managed_database       = true
      managed_cache          = true
      nat_gateway_count      = 1
      interface_endpoints    = []
      internal_load_balancer = false
      instances_are_public   = false
      persistent_volume      = false
    }

    distributed = {
      groups = {
        backend       = ["backend"]
        frontend      = ["frontend"]
        landing       = ["landing"]
        docs          = ["docs"]
        opa           = ["opa"]
        celery-worker = ["celery-worker"]
        celery-beat   = ["celery-beat"]
      }
      managed_database       = true
      managed_cache          = true
      nat_gateway_count      = null # one per availability zone
      interface_endpoints    = ["ssm", "ssmmessages", "ec2messages", "ecr.api", "ecr.dkr"]
      internal_load_balancer = true
      instances_are_public   = false
      persistent_volume      = false
    }
  }

  preset = local.topology_presets[var.topology]

  # Every override defaults to the preset, so a tfvars file can deviate on one
  # axis — adding interface endpoints to a consolidated deployment, say —
  # without leaving the preset behind entirely.
  groups                 = local.preset.groups
  managed_database       = coalesce(var.managed_database, local.preset.managed_database)
  managed_cache          = coalesce(var.managed_cache, local.preset.managed_cache)
  interface_endpoints    = coalesce(var.interface_endpoints, local.preset.interface_endpoints)
  internal_load_balancer = coalesce(var.internal_load_balancer, local.preset.internal_load_balancer)
  instances_are_public   = local.preset.instances_are_public
  persistent_volume      = local.preset.persistent_volume

  nat_gateway_count = coalesce(
    var.nat_gateway_count,
    local.preset.nat_gateway_count,
    var.availability_zone_count,
  )

  # ----------------------------------------------------------------------
  # Derived from the group assignment
  # ----------------------------------------------------------------------

  # group => the public services it must be registered with at the load balancer
  group_public_services = {
    for group, services in local.groups :
    group => [for svc in services : svc if contains(keys(local.public_services), svc)]
  }

  group_internal_services = {
    for group, services in local.groups :
    group => [for svc in services : svc if contains(keys(local.internal_services), svc)]
  }

  # Which group runs each service, so the edge module can point a target group
  # at the right Auto Scaling group.
  service_group = merge([
    for group, services in local.groups : { for svc in services : svc => group }
  ]...)

  # A group needs data-tier access if any service it runs opens such a
  # connection. In single_host that is the same group as everything else.
  data_client_groups = [
    for group, services in local.groups :
    group if length(setintersection(toset(services), toset(local.data_client_services))) > 0
  ]

  # Per-group permission flags, resolved to booleans *here* so the module block
  # that consumes them contains no operators.
  #
  # python-hcl2 — the parser production uses, and therefore the one
  # scripts/validate_deploy_terraform.py scans with — cannot parse a comparison
  # inside a nested object within a for-expression. It handles the same
  # comparison at the top level of a for-expression fine, which is the form
  # used below. An unparseable file is a file the gate silently skips, so this
  # is worth the indirection.
  artifact_services = ["backend", "celery-worker"]

  group_reads_secrets = {
    for group, services in local.groups :
    group => length(setintersection(toset(services), toset(local.data_client_services))) > 0
  }

  group_uses_artifacts = {
    for group, services in local.groups :
    group => length(setintersection(toset(services), toset(local.artifact_services))) > 0
  }

  # Where the backend finds the policy server: behind the internal load
  # balancer when OPA has its own hosts, over the Docker network when it shares
  # one. Same parser constraint as above — kept out of ssm.tf as a ternary.
  opa_internal_url = "http://${module.edge.internal_alb_dns_name}:${local.service_topology["opa"].host_port}"
  opa_url          = local.internal_load_balancer ? local.opa_internal_url : "http://opa:8181"

  # Where the instances live. A group with no NAT gateway sits in the public
  # tier for egress; the one that owns the state volume is pinned to a single
  # subnet because an EBS volume cannot cross availability zones.
  public_instance_subnets = local.persistent_volume ? slice(module.network.public_subnet_ids, 0, 1) : module.network.public_subnet_ids
  instance_subnet_ids     = local.instances_are_public ? local.public_instance_subnets : module.network.private_subnet_ids

  # Which groups carry a target-tracking policy, and on what. A group name is
  # only present here when that service has hosts of its own — `worker` in the
  # consolidated topology, `celery-worker` and `opa` in the distributed one.
  # Expressed as a lookup rather than a ternary chain so the module block stays
  # free of operators the scanner's parser cannot read.
  scaling_policies = {
    worker        = { metric = "cpu", target_value = var.celery_worker_target_cpu }
    celery-worker = { metric = "cpu", target_value = var.celery_worker_target_cpu }
    opa           = { metric = "requests", target_value = var.opa_target_requests_per_instance }
  }

  # Only the OPA group scales on request count, and only it needs the internal
  # load balancer's dimensions to do it.
  group_alb_arn_suffix = {
    opa = module.edge.internal_alb_arn_suffix
  }

  group_target_group_arn_suffix = {
    opa = module.edge.internal_target_group_arn_suffix
  }

  postgres_server = local.managed_database ? module.data.postgres_address : "db"
  postgres_port   = local.managed_database ? module.data.postgres_port : "5432"
  redis_url       = local.managed_cache ? module.data.redis_url : "redis://redis:6379/0"

  # Only reachable services need a port opened on the group's security group.
  group_ports = {
    for group, services in local.groups :
    group => [
      for svc in services :
      local.service_topology[svc].host_port
      if local.service_topology[svc].host_port != null
    ]
  }

  # ----------------------------------------------------------------------
  # Hostnames and URLs
  # ----------------------------------------------------------------------

  hostnames = {
    backend  = "${var.api_subdomain}.${var.domain_name}"
    frontend = "${var.app_subdomain}.${var.domain_name}"
    docs     = "${var.docs_subdomain}.${var.domain_name}"
    landing  = var.domain_name
  }

  urls = { for svc, host in local.hostnames : svc => "https://${host}" }

  # ----------------------------------------------------------------------
  # Parameter Store layout
  # ----------------------------------------------------------------------

  ssm_prefix = "/${var.project}/${var.environment}"
}
