# METADATA
# title: RDS instance keeps no automated backups
# description: An RDS instance has a backup retention period of zero, which switches automated backups off entirely. That does not only mean there is no nightly snapshot — it means point-in-time recovery is disabled, so the granularity of any restore is whatever manual snapshot somebody last remembered to take. The failure this protects against is rarely hardware; it is a bad migration or a DELETE without a WHERE clause, where the recovery target is a specific minute and a week-old snapshot is not an answer.
# custom:
#   severity: high
#   detection: cloud_posture
#   examples:
#     bad: |
#       aws rds modify-db-instance --db-instance-identifier prod \
#         --backup-retention-period 0 --apply-immediately
#     good: |
#       aws rds modify-db-instance --db-instance-identifier prod \
#         --backup-retention-period 7 --apply-immediately
#     fix: |
#       Set a retention period of at least seven days. Enabling it on a running instance causes a brief outage as the first snapshot is taken, so schedule it — but do schedule it, because the window where this matters is not one you get to choose.
package greensecops.cloud_aws.reliability.rds_no_backup_retention

import rego.v1

violations contains violation if {
	some db in input.rds_instances

	db.backup_retention_days == 0

	violation := {
		"rule": "rds_no_backup_retention",
		"severity": "high",
		"category": "reliability",
		"resource_type": "aws_db_instance",
		"resource_id": db.id,
		"region": db.region,
		"message": sprintf("Database '%v' has automated backups switched off, so there is no point-in-time recovery — only whatever manual snapshot exists.", [db.id]),
	}
}
