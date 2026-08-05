# METADATA
# title: RDS instance does not take minor version upgrades
# description: An RDS instance has automatic minor version upgrades switched off, so it stays on whatever patch release it was created with. Minor versions are where engine security fixes ship, and skipping them does not just accumulate risk — it accumulates *distance*, because AWS eventually forces a major upgrade and the further behind the instance is, the larger and less reversible that step becomes. The usual reason it is off is a worry about surprise restarts, which the maintenance window already answers.
# custom:
#   severity: medium
#   detection: cloud_posture
#   examples:
#     bad: |
#       aws rds create-db-instance --db-instance-identifier prod --engine postgres \
#         --no-auto-minor-version-upgrade
#     good: |
#       aws rds create-db-instance --db-instance-identifier prod --engine postgres \
#         --auto-minor-version-upgrade \
#         --preferred-maintenance-window "sun:03:00-sun:04:00"
#     fix: |
#       Enable auto minor version upgrade and set a maintenance window when a brief failover is acceptable. On a Multi-AZ instance the upgrade applies to the standby first, so the visible impact is a failover rather than an outage.
package greensecops.cloud_aws.maintainability.rds_auto_minor_upgrade_disabled

import rego.v1

violations contains violation if {
	some db in input.rds_instances

	db.auto_minor_version_upgrade == false

	violation := {
		"rule": "rds_auto_minor_upgrade_disabled",
		"severity": "medium",
		"category": "maintainability",
		"resource_type": "aws_db_instance",
		"resource_id": db.id,
		"region": db.region,
		"message": sprintf("Database '%v' does not take automatic minor upgrades, so engine security fixes accumulate until a forced major upgrade.", [db.id]),
	}
}
