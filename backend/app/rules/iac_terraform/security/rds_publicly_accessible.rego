# METADATA
# title: RDS instance is publicly accessible
# description: An aws_db_instance sets publicly_accessible = true, so RDS gives it a public IP and the database is reachable from the internet rather than only from inside the VPC. Its security group is then the only thing between the database and the world, and the same rds_publicly_accessible rule in the cloud engine exists because this is one of the most reliably exploited misconfigurations there is.
# custom:
#   severity: critical
#   detection: static_analysis
#   examples:
#     bad: |
#       resource "aws_db_instance" "main" {
#         identifier          = "app-db"
#         publicly_accessible = true
#       }
#     good: |
#       resource "aws_db_instance" "main" {
#         identifier          = "app-db"
#         publicly_accessible = false
#       }
#     fix: |
#       Set publicly_accessible = false and place the instance in private subnets. Reach it from outside the VPC through a bastion or a VPN rather than by exposing the endpoint.
package greensecops.iac_terraform.security.rds_publicly_accessible

import rego.v1

violations contains violation if {
	some res in input.resource
	some name, db in res.aws_db_instance
	db.publicly_accessible == true
	violation := {
		"rule": "rds_publicly_accessible",
		"severity": "critical",
		"category": "security",
		"resource_address": sprintf("aws_db_instance.%v", [name]),
		"file_path": object.get(db, "__tf_file", ""),
		"line_start": object.get(db, "__start_line__", null),
		"line_end": object.get(db, "__end_line__", null),
		"message": sprintf("RDS instance '%v' is publicly accessible, so its endpoint resolves to a public IP reachable from the internet.", [name]),
	}
}
