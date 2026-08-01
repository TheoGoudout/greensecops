# Tier A — the distributed topology.
#
# The lines to change in an existing env/<environment>.tfvars once individual
# services need to scale independently. Reached from `consolidated`, not
# directly from `single_host`.
#
# What changes, concretely:
#   * One host group per service. The Celery workers scale on CPU and OPA on
#     requests per instance; the rest are fixed-size groups.
#   * An internal load balancer appears in front of OPA, replacing the Docker
#     network path the backend used to reach it by.
#   * NAT gateways go to one per availability zone, and PrivateLink endpoints
#     appear for the SSM and ECR paths.
#   * PostgreSQL becomes Multi-AZ.
#
# The endpoint list is the single largest cost line here — roughly $8 per
# endpoint per availability zone per month. Add one only when the NAT
# data-processing charge it displaces exceeds that.

topology = "distributed"

groups = {
  backend       = { instance_type = "t4g.medium", min = 2, max = 4, desired = 2 }
  frontend      = { instance_type = "t4g.small", min = 2, max = 2, desired = 2 }
  landing       = { instance_type = "t4g.small", min = 2, max = 2, desired = 2 }
  docs          = { instance_type = "t4g.small", min = 2, max = 2, desired = 2 }
  celery-worker = { instance_type = "t4g.medium", min = 2, max = 10, desired = 2 }
  celery-beat   = { instance_type = "t4g.small", min = 1, max = 1, desired = 1 }
  opa           = { instance_type = "t4g.small", min = 2, max = 6, desired = 2 }
}

availability_zone_count = 3

postgres_instance_class        = "db.m7g.large"
postgres_allocated_storage     = 100
postgres_multi_az              = true
postgres_backup_retention_days = 30

redis_node_type     = "cache.t4g.small"
redis_replica_count = 1

# Overrides the topology default of one NAT per AZ, if the availability
# trade is acceptable — see the cost table in deploy/README.md.
# nat_gateway_count = 1

# Overrides the topology default endpoint list. Empty is cheapest.
# interface_endpoints = []
