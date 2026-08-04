# METADATA
# title: Variable without a description
# description: A variable block has no description, making it harder for other authors (and module consumers) to understand its purpose without reading the whole config.
# custom:
#   severity: low
#   severity_weight: 0.4
#   detection: static_analysis
#   examples:
#     bad: |
#       variable "region" {
#         type = string
#       }
#     good: |
#       variable "region" {
#         type        = string
#         description = "AWS region to deploy into."
#       }
#     fix: |
#       Add a description to every variable block.
package greensecops.iac_terraform.maintainability.variable_missing_description

import rego.v1

violations contains violation if {
	some named in input.variable
	some name, attrs in named
	not attrs.description
	violation := {
		"rule": "variable_missing_description",
		"severity": "low",
		"category": "maintainability",
		"resource_address": sprintf("var.%v", [name]),
		"file_path": object.get(attrs, "__tf_file", ""),
		"line_start": object.get(attrs, "__start_line__", null),
		"line_end": object.get(attrs, "__end_line__", null),
		"message": sprintf(
			"Variable '%v' has no description — harder for other authors to understand its purpose.",
			[name],
		),
	}
}
