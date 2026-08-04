# METADATA
# title: RDS instance has no deletion protection
# description: An aws_db_instance does not enable deletion_protection, so a terraform destroy, a renamed resource, or any change Terraform decides to apply by replacement will delete the database and its data. Terraform is exactly the tool that makes this easy to do by accident, because the destroy is a consequence of an edit somewhere else in the configuration rather than a deliberate command.
# custom:
#   severity: medium
#   detection: static_analysis
#   examples:
#     bad: |
#       resource "aws_db_instance" "main" {
#         identifier = "app-db"
#       }
#     good: |
#       resource "aws_db_instance" "main" {
#         identifier          = "app-db"
#         deletion_protection = true
#       }
#     fix: |
#       Set deletion_protection = true. Deleting the instance then needs the flag turned off first, which is the deliberate second step this is for. Pair it with a lifecycle prevent_destroy block for the same reason.
package greensecops.iac_terraform.reliability.rds_no_deletion_protection

import rego.v1

violations contains violation if {
	some res in input.resource
	some name, db in res.aws_db_instance
	not _protected(db)
	violation := {
		"rule": "rds_no_deletion_protection",
		"severity": "medium",
		"category": "reliability",
		"resource_address": sprintf("aws_db_instance.%v", [name]),
		"file_path": object.get(db, "__tf_file", ""),
		"line_start": object.get(db, "__start_line__", null),
		"line_end": object.get(db, "__end_line__", null),
		"message": sprintf("RDS instance '%v' has no deletion protection, so a replacement or a destroy takes the database and its data with it.", [name]),
	}
}

_protected(db) if db.deletion_protection == true

# hcl2 does not evaluate expressions, so `deletion_protection =
# var.postgres_deletion_protection` arrives as the string
# "${var.postgres_deletion_protection}". The value is unknowable here, but a
# module that takes the setting as an input has made the decision deliberately
# — treating a reference as `false` would report every parameterised module.
_protected(db) if {
	value := db.deletion_protection
	is_string(value)
	trim_space(value) != ""
}
