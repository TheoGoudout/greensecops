# METADATA
# title: Unencrypted EBS volume
# description: An aws_ebs_volume resource has no encrypted = true, leaving data at rest unencrypted.
# custom:
#   severity: high
#   detection: static_analysis
#   examples:
#     bad: |
#       resource "aws_ebs_volume" "data" {
#         size = 100
#       }
#     good: |
#       resource "aws_ebs_volume" "data" {
#         size      = 100
#         encrypted = true
#       }
#     fix: |
#       Add encrypted = true (and kms_key_id if a customer-managed key is required).
package greensecops.iac_terraform.security.unencrypted_ebs_volume

import rego.v1

violations contains violation if {
	some res in input.resource
	some name, vol in res.aws_ebs_volume
	not vol.encrypted == true
	violation := {
		"rule": "unencrypted_ebs_volume",
		"severity": "high",
		"category": "security",
		"resource_address": sprintf("aws_ebs_volume.%v", [name]),
		"file_path": object.get(vol, "__tf_file", ""),
		"line_start": object.get(vol, "__start_line__", null),
		"line_end": object.get(vol, "__end_line__", null),
		"message": sprintf("EBS volume '%v' has no encrypted = true — data at rest is unencrypted.", [name]),
	}
}
