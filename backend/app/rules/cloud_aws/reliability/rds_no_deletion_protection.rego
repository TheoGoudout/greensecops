# METADATA
# title: RDS instance can be deleted without a guard
# description: An RDS instance has deletion protection off, so a single API call, a mistyped identifier or a Terraform plan nobody read closely destroys it. This is the cheapest control in the whole account — it costs nothing, changes no behaviour, and the only thing it does is require somebody to turn it off deliberately before a deletion succeeds. That extra step is the entire point, because the deletions that hurt are the ones nobody meant to make.
# custom:
#   severity: medium
#   detection: cloud_posture
#   examples:
#     bad: |
#       aws rds create-db-instance --db-instance-identifier prod --engine postgres
#     good: |
#       aws rds create-db-instance --db-instance-identifier prod --engine postgres \
#         --deletion-protection
#     fix: |
#       Run `aws rds modify-db-instance --db-instance-identifier <id> --deletion-protection`. If Terraform manages the instance, set `deletion_protection = true` there too, or the next apply will turn it back off.
package greensecops.cloud_aws.reliability.rds_no_deletion_protection

import rego.v1

violations contains violation if {
	some db in input.rds_instances

	db.deletion_protection == false

	violation := {
		"rule": "rds_no_deletion_protection",
		"severity": "medium",
		"category": "reliability",
		"resource_type": "aws_db_instance",
		"resource_id": db.id,
		"region": db.region,
		"message": sprintf("Database '%v' has no deletion protection, so one API call destroys it with nothing to confirm the intent.", [db.id]),
	}
}
