# METADATA
# title: Variable without a type constraint
# description: A variable block declares no type, so Terraform accepts any value for it. A number passed as a string, or an object missing a key, is then only caught wherever the value is finally used — which for infrastructure means at apply time, against real resources, halfway through a change. A type constraint moves that failure to plan time, and it documents the shape a caller has to supply, which a description alone cannot do precisely.
# custom:
#   severity: low
#   detection: static_analysis
#   examples:
#     bad: |
#       variable "subnet_ids" {
#         description = "Subnets the service runs in."
#       }
#     good: |
#       variable "subnet_ids" {
#         description = "Subnets the service runs in."
#         type        = list(string)
#       }
#     fix: |
#       Add a type. Prefer the most specific one that fits — list(string) over list(any), and an object({...}) over map(any) — since the value of the constraint is exactly the precision it carries.
package greensecops.iac_terraform.maintainability.variable_missing_type

import rego.v1

violations contains violation if {
	some block in input.variable
	some name, attrs in block
	is_object(attrs)
	not _has_type(attrs)

	violation := {
		"rule": "variable_missing_type",
		"severity": "low",
		"category": "maintainability",
		"resource_address": sprintf("var.%v", [name]),
		"file_path": object.get(attrs, "__tf_file", ""),
		"line_start": object.get(attrs, "__start_line__", null),
		"line_end": object.get(attrs, "__end_line__", null),
		"message": sprintf("Variable '%v' has no type constraint, so a wrongly-shaped value is only caught at apply time.", [name]),
	}
}

# hcl2 renders `type = string` as the expression string "${string}", so any
# non-empty value here means a constraint was written.
_has_type(attrs) if {
	type_value := attrs.type
	is_string(type_value)
	trim_space(type_value) != ""
}
