# Tier B — the consolidated topology.
#
# Not a separate environment: these are the lines to change in an existing
# env/<environment>.tfvars when a single host stops being enough. Everything
# else in that file stays as it is.
#
# What changes, concretely:
#   * Three host groups instead of one — static sites, API + policy, workers.
#     Every tier survives losing an instance.
#   * PostgreSQL moves to RDS and Redis to ElastiCache. The state volume and
#     its snapshots are no longer used; RDS brings point-in-time recovery.
#   * One NAT gateway appears, and the instances move to private subnets.
#
# This is a data migration, not just an apply — see the migration section of
# deploy/README.md before running it.

topology = "consolidated"

groups = {
  web    = { instance_type = "t4g.small", min = 2, max = 2, desired = 2 }
  app    = { instance_type = "t4g.medium", min = 2, max = 4, desired = 2 }
  worker = { instance_type = "t4g.medium", min = 2, max = 8, desired = 2 }
}

# Managed data tier. Single-AZ to start: the step up to Multi-AZ doubles the
# instance cost and is worth taking on its own evidence.
postgres_instance_class        = "db.t4g.medium"
postgres_allocated_storage     = 50
postgres_multi_az              = false
postgres_backup_retention_days = 14

redis_node_type     = "cache.t4g.micro"
redis_replica_count = 0
