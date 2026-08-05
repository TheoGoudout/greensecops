# METADATA
# title: RDS instance runs in a single availability zone
# description: An RDS instance has no standby in a second availability zone, so an AZ failure or a storage-level fault takes the database down until a restore completes — hours, not the minute or so a Multi-AZ failover takes. It also makes routine maintenance disruptive rather than invisible, since patching a single-AZ instance means downtime while a Multi-AZ one fails over to the patched standby. That second effect is the one people notice first, and it is why single-AZ tends to make an instance harder to keep current as well as less available.
# custom:
#   severity: medium
#   detection: cloud_posture
#   examples:
#     bad: |
#       aws rds create-db-instance --db-instance-identifier prod \
#         --engine postgres --db-instance-class db.m6g.large
#     good: |
#       aws rds create-db-instance --db-instance-identifier prod \
#         --engine postgres --db-instance-class db.m6g.large --multi-az
#     fix: |
#       Enable Multi-AZ on the instance. It roughly doubles the instance cost and can be applied to a running database — the conversion itself is online, with a short failover at the end. A non-production database is a reasonable place to decline this deliberately.
package greensecops.cloud_aws.reliability.rds_not_multi_az

import rego.v1

violations contains violation if {
	some db in input.rds_instances

	db.multi_az == false

	violation := {
		"rule": "rds_not_multi_az",
		"severity": "medium",
		"category": "reliability",
		"resource_type": "aws_db_instance",
		"resource_id": db.id,
		"region": db.region,
		"message": sprintf("Database '%v' has no standby in a second availability zone, so an AZ failure means a restore rather than a failover.", [db.id]),
	}
}
