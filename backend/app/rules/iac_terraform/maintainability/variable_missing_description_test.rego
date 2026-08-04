package greensecops.iac_terraform.maintainability.variable_missing_description_test

import data.greensecops.iac_terraform.maintainability.variable_missing_description as variable_undescribed
import rego.v1

# `variable` nests one level shallower than resource/data: {name: attrs}.

_variable(name, attrs) := {"variable": [{name: object.union(
	{"__tf_file": "variables.tf", "__start_line__": 3, "__end_line__": 6},
	attrs,
)}]}

test_violation_when_no_description_is_given if {
	violations := variable_undescribed.violations with input as _variable("region", {"type": "${string}"})
	count(violations) == 1
	some v in violations
	v.resource_address == "var.region"
	v.file_path == "variables.tf"
}

test_no_violation_with_a_description if {
	violations := variable_undescribed.violations with input as _variable("region", {
		"description": "AWS region to deploy into.",
		"type": "${string}",
	})
	count(violations) == 0
}

# A variable can lack a description and a type both; each rule reports its own.
test_fires_independently_of_variable_missing_type if {
	violations := variable_undescribed.violations with input as _variable("region", {"default": "eu-west-1"})
	count(violations) == 1
}

test_no_violation_when_there_are_no_variables if {
	violations := variable_undescribed.violations with input as {"variable": []}
	count(violations) == 0
}

test_each_undescribed_variable_is_its_own_finding if {
	violations := variable_undescribed.violations with input as {"variable": [
		{"a": {"type": "${string}"}},
		{"b": {"type": "${string}"}},
		{"c": {"description": "documented", "type": "${string}"}},
	]}
	count(violations) == 2
	{v.resource_address | some v in violations} == {"var.a", "var.b"}
}
