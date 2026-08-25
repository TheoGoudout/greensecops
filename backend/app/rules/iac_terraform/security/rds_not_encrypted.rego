# METADATA
# title: RDS instance not encrypted at rest
# description: An aws_db_instance resource has no storage_encrypted = true, leaving the database's data at rest unencrypted.
# custom:
#   severity: high
#   detection: static_analysis
#   examples:
#     bad: |
#       resource "aws_db_instance" "primary" {
#         engine = "postgres"
#       }
#     good: |
#       resource "aws_db_instance" "primary" {
#         engine             = "postgres"
#         storage_encrypted  = true
#       }
#     fix: |
#       Add storage_encrypted = true. For an existing unencrypted instance this requires a snapshot-and-restore, not an in-place change — plan a migration window.
package greensecops.iac_terraform.security.rds_not_encrypted

import data.greensecops.lib.terraform as tf
import rego.v1

violations contains violation if {
	some res in input.resource
	some name, db in res.aws_db_instance

	# `not db.storage_encrypted == true` fired on every module that takes the
	# setting as an input: hcl2 hands `storage_encrypted = var.encrypt` back as
	# the string "${var.encrypt}", which is not `true`. Four sibling rules each
	# carried a private "a reference is not false" helper for exactly this and
	# this one carried none — see lib/terraform.rego.
	not tf.is_enabled(object.get(db, "storage_encrypted", false))
	violation := {
		"rule": "rds_not_encrypted",
		"severity": "high",
		"category": "security",
		"resource_address": sprintf("aws_db_instance.%v", [name]),
		"file_path": object.get(db, "__tf_file", ""),
		"line_start": object.get(db, "__start_line__", null),
		"line_end": object.get(db, "__end_line__", null),
		"message": sprintf("RDS instance '%v' has no storage_encrypted = true — data at rest is unencrypted.", [name]),
	}
}
