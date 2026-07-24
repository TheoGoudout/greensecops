# METADATA
# title: RDS instance not encrypted at rest
# description: A live RDS instance has StorageEncrypted set to false, leaving its data at rest unencrypted.
# custom:
#   severity: high
#   detection: cloud_posture
#   examples:
#     bad: |
#       aws rds describe-db-instances --db-instance-identifier prod-db
#       # StorageEncrypted: false
#     good: |
#       aws rds describe-db-instances --db-instance-identifier prod-db
#       # StorageEncrypted: true
#     fix: |
#       Storage encryption can't be enabled on an existing instance — snapshot it, copy the snapshot with encryption enabled, and restore from the encrypted copy.
package greensecops.cloud_aws.security.rds_not_encrypted

import rego.v1

violations contains violation if {
	some db in input.rds_instances
	not db.storage_encrypted
	violation := {
		"rule": "rds_not_encrypted",
		"severity": "high",
		"category": "security",
		"resource_type": "aws_db_instance",
		"resource_id": db.id,
		"region": db.region,
		"message": sprintf("RDS instance '%v' is not encrypted at rest.", [db.id]),
	}
}
