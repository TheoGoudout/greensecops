package greensecops.iac_terraform.maintainability.output_missing_description_test

import data.greensecops.iac_terraform.maintainability.output_missing_description as output_undescribed
import rego.v1

# `output` nests one level shallower than resource/data: {name: attrs}, not
# {type: {name: attrs}}.

_output(name, attrs) := {"output": [{name: object.union(
	{"__tf_file": "outputs.tf", "__start_line__": 3, "__end_line__": 6},
	attrs,
)}]}

test_violation_when_no_description_is_given if {
	violations := output_undescribed.violations with input as _output("endpoint", {"value": "${aws_db_instance.main.address}"})
	count(violations) == 1
	some v in violations
	v.resource_address == "output.endpoint"
	v.file_path == "outputs.tf"
	v.line_start == 3
}

test_no_violation_with_a_description if {
	violations := output_undescribed.violations with input as _output("endpoint", {
		"description": "Hostname of the primary database.",
		"value": "${aws_db_instance.main.address}",
	})
	count(violations) == 0
}

# An empty or whitespace-only description satisfies nothing.
test_violation_for_an_empty_description if {
	violations := output_undescribed.violations with input as _output("endpoint", {"description": "", "value": "x"})
	count(violations) == 1
}

test_violation_for_a_whitespace_only_description if {
	violations := output_undescribed.violations with input as _output("endpoint", {"description": "   ", "value": "x"})
	count(violations) == 1
}

test_no_violation_when_there_are_no_outputs if {
	violations := output_undescribed.violations with input as {"output": []}
	count(violations) == 0
}

test_each_undescribed_output_is_its_own_finding if {
	violations := output_undescribed.violations with input as {"output": [
		{"endpoint": {"value": "a", "__tf_file": "outputs.tf", "__start_line__": 1, "__end_line__": 3}},
		{"port": {"value": "b", "__tf_file": "outputs.tf", "__start_line__": 5, "__end_line__": 7}},
		{"name": {"description": "The name.", "value": "c", "__tf_file": "outputs.tf", "__start_line__": 9, "__end_line__": 12}},
	]}
	count(violations) == 2
	{v.resource_address | some v in violations} == {"output.endpoint", "output.port"}
}
