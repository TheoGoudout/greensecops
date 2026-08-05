# METADATA
# title: Output without a description
# description: An output block has no description. Outputs are a module's public interface — they are what `terraform output` prints and what a calling module consumes — so an undescribed one leaves the caller to infer from the name alone what the value is and whether it is safe to depend on. This is the output-side counterpart of variable_missing_description, and the two together are what make a module usable without reading its body.
# custom:
#   severity: low
#   detection: static_analysis
#   examples:
#     bad: |
#       output "endpoint" {
#         value = aws_db_instance.main.address
#       }
#     good: |
#       output "endpoint" {
#         description = "Hostname of the primary database, for use in application connection strings."
#         value       = aws_db_instance.main.address
#       }
#     fix: |
#       Add a description saying what the value is and what a caller would use it for. Mark it sensitive = true as well if it carries a credential or an endpoint you would not want in CI logs.
package greensecops.iac_terraform.maintainability.output_missing_description

import rego.v1

violations contains violation if {
	some block in input.output
	some name, attrs in block
	is_object(attrs)
	not _has_description(attrs)

	violation := {
		"rule": "output_missing_description",
		"severity": "low",
		"category": "maintainability",
		"resource_address": sprintf("output.%v", [name]),
		"file_path": object.get(attrs, "__tf_file", ""),
		"line_start": object.get(attrs, "__start_line__", null),
		"line_end": object.get(attrs, "__end_line__", null),
		"message": sprintf("Output '%v' has no description, so a caller has only the name to go on.", [name]),
	}
}

_has_description(attrs) if {
	description := attrs.description
	is_string(description)
	trim_space(description) != ""
}
