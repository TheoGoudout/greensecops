# METADATA
# title: Hardcoded AWS access key
# description: A resource attribute contains a literal string matching the AWS access key ID format (AKIA...), rather than a variable or a secrets-manager reference.
# custom:
#   severity: critical
#   detection: static_analysis
#   examples:
#     bad: |
#       resource "aws_instance" "app" {
#         user_data = "AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE"
#       }
#     good: |
#       resource "aws_instance" "app" {
#         user_data = "AWS_ACCESS_KEY_ID=${var.access_key_id}"
#       }
#     fix: |
#       Remove the literal key, pass it via a variable sourced from a secrets manager (AWS Secrets Manager, SSM Parameter Store), and rotate the exposed key.
package greensecops.iac_terraform.security.hardcoded_credentials_in_tf

import rego.v1

_akid_pattern := `AKIA[0-9A-Z]{16}`

violations contains violation if {
	some res in input.resource
	some res_type, named in res
	some name, attrs in named
	walk(attrs, [_, value])
	is_string(value)
	regex.match(_akid_pattern, value)
	violation := {
		"rule": "hardcoded_credentials_in_tf",
		"severity": "critical",
		"category": "security",
		"resource_address": sprintf("%v.%v", [res_type, name]),
		"file_path": object.get(attrs, "__tf_file", ""),
		"line_start": object.get(attrs, "__start_line__", null),
		"line_end": object.get(attrs, "__end_line__", null),
		"message": sprintf("Resource '%v.%v' has a hardcoded AWS access key ID literal.", [res_type, name]),
	}
}
