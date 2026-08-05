package greensecops.iac_terraform.maintainability.variable_missing_type_test

import data.greensecops.iac_terraform.maintainability.variable_missing_type
import rego.v1

# hcl2 renders `type = list(string)` as the expression string
# "${list(string)}" rather than a structured value, so any non-empty string
# here means a constraint was written.

_variable(name, attrs) := {"variable": [{name: object.union(
	{"__tf_file": "variables.tf", "__start_line__": 3, "__end_line__": 6},
	attrs,
)}]}

test_violation_when_no_type_is_given if {
	violations := variable_missing_type.violations with input as _variable("subnet_ids", {"description": "Subnets the service runs in."})
	count(violations) == 1
	some v in violations
	v.resource_address == "var.subnet_ids"
	v.file_path == "variables.tf"
}

test_no_violation_with_a_simple_type if {
	violations := variable_missing_type.violations with input as _variable("region", {
		"description": "AWS region.",
		"type": "${string}",
	})
	count(violations) == 0
}

test_no_violation_with_a_complex_type if {
	violations := variable_missing_type.violations with input as _variable("subnet_ids", {
		"description": "Subnets the service runs in.",
		"type": "${list(string)}",
	})
	count(violations) == 0
}

test_violation_for_an_empty_type if {
	violations := variable_missing_type.violations with input as _variable("region", {"type": ""})
	count(violations) == 1
}

# A variable can lack a type and a description both; each rule reports its own.
test_fires_independently_of_variable_missing_description if {
	violations := variable_missing_type.violations with input as _variable("region", {"default": "eu-west-1"})
	count(violations) == 1
}

test_no_violation_when_there_are_no_variables if {
	violations := variable_missing_type.violations with input as {"variable": []}
	count(violations) == 0
}

test_each_untyped_variable_is_its_own_finding if {
	violations := variable_missing_type.violations with input as {"variable": [
		{"a": {"description": "x", "__tf_file": "variables.tf", "__start_line__": 1, "__end_line__": 3}},
		{"b": {"description": "y", "__tf_file": "variables.tf", "__start_line__": 5, "__end_line__": 7}},
		{"c": {"type": "${string}", "__tf_file": "variables.tf", "__start_line__": 9, "__end_line__": 11}},
	]}
	count(violations) == 2
	{v.resource_address | some v in violations} == {"var.a", "var.b"}
}
