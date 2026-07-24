# METADATA
# title: RDS instance is publicly accessible
# description: A live RDS instance has PubliclyAccessible set to true, giving it a public endpoint reachable from the internet rather than only from within its VPC.
# custom:
#   severity: critical
#   detection: cloud_posture
#   examples:
#     bad: |
#       aws rds describe-db-instances --db-instance-identifier prod-db
#       # PubliclyAccessible: true
#     good: |
#       aws rds modify-db-instance --db-instance-identifier prod-db --no-publicly-accessible
#     fix: |
#       Disable public accessibility and reach the database through a bastion, VPN, or app servers inside the VPC.
package greensecops.cloud_aws.security.rds_publicly_accessible

import rego.v1

violations contains violation if {
	some db in input.rds_instances
	db.publicly_accessible
	violation := {
		"rule": "rds_publicly_accessible",
		"severity": "critical",
		"category": "security",
		"resource_type": "aws_db_instance",
		"resource_id": db.id,
		"region": db.region,
		"message": sprintf("RDS instance '%v' is publicly accessible.", [db.id]),
	}
}
