# METADATA
# title: RDS instance keeps no automated backups
# description: An aws_db_instance sets backup_retention_period = 0, which disables automated backups entirely. With no backups there are also no point-in-time restores, so any data loss — a bad migration, a mistaken delete, a corrupted write — is permanent. The setting is also the default for a bare instance resource, so this is more often an omission than a decision.
# custom:
#   severity: high
#   detection: static_analysis
#   examples:
#     bad: |
#       resource "aws_db_instance" "main" {
#         identifier              = "app-db"
#         backup_retention_period = 0
#       }
#     good: |
#       resource "aws_db_instance" "main" {
#         identifier              = "app-db"
#         backup_retention_period = 7
#       }
#     fix: |
#       Set backup_retention_period to at least 7 days, and set a backup_window outside peak hours. Retention is what enables point-in-time recovery, not just the daily snapshot.
package greensecops.iac_terraform.reliability.rds_no_backup_retention

import rego.v1

violations contains violation if {
	some res in input.resource
	some name, db in res.aws_db_instance
	db.backup_retention_period == 0
	violation := {
		"rule": "rds_no_backup_retention",
		"severity": "high",
		"category": "reliability",
		"resource_address": sprintf("aws_db_instance.%v", [name]),
		"file_path": object.get(db, "__tf_file", ""),
		"line_start": object.get(db, "__start_line__", null),
		"line_end": object.get(db, "__end_line__", null),
		"message": sprintf("RDS instance '%v' has backup_retention_period = 0, so it takes no automated backups and cannot be restored to a point in time.", [name]),
	}
}
