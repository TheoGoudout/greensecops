package greensecops.ci_workflow.security.checkout_persists_credentials_test

import data.greensecops.ci_workflow.security.checkout_persists_credentials as persists
import rego.v1

_workflow(steps) := {"jobs": {"build": {
	"runs-on": "ubuntu-latest",
	"steps": steps,
	"__start_line__": 4,
	"__end_line__": 20,
}}}

_checkout(with_block) := {
	"uses": "actions/checkout@v4",
	"with": with_block,
	"__start_line__": 6,
	"__end_line__": 8,
}

test_violation_when_checkout_has_no_with_block if {
	violations := persists.violations with input as _workflow([{
		"uses": "actions/checkout@v4",
		"__start_line__": 6,
		"__end_line__": 6,
	}])
	count(violations) == 1
	some v in violations
	v.job == "build"
	v.step_index == 0
}

test_violation_when_the_with_block_does_not_disable_it if {
	violations := persists.violations with input as _workflow([_checkout({"fetch-depth": 0})])
	count(violations) == 1
}

test_no_violation_when_credentials_are_not_persisted if {
	violations := persists.violations with input as _workflow([_checkout({"persist-credentials": false})])
	count(violations) == 0
}

# YAML quoting turns the boolean into a string often enough to matter.
test_no_violation_for_the_quoted_string_form if {
	violations := persists.violations with input as _workflow([_checkout({"persist-credentials": "false"})])
	count(violations) == 0
}

test_violation_when_it_is_explicitly_true if {
	violations := persists.violations with input as _workflow([_checkout({"persist-credentials": true})])
	count(violations) == 1
}

test_no_violation_for_a_workflow_that_does_not_check_out if {
	violations := persists.violations with input as _workflow([{
		"uses": "actions/setup-node@v4",
		"__start_line__": 6,
		"__end_line__": 6,
	}])
	count(violations) == 0
}

test_no_violation_for_a_run_step if {
	violations := persists.violations with input as _workflow([{
		"run": "git clone https://example.invalid/repo",
		"__start_line__": 6,
		"__end_line__": 6,
	}])
	count(violations) == 0
}

test_the_finding_carries_the_step_line_span if {
	violations := persists.violations with input as _workflow([_checkout({"fetch-depth": 0})])
	some v in violations
	v.line_start == 6
	v.line_end == 8
}

test_each_checkout_is_its_own_finding if {
	violations := persists.violations with input as _workflow([
		_checkout({"fetch-depth": 0}),
		{"run": "npm ci"},
		_checkout({"path": "vendor"}),
	])
	count(violations) == 2
	count({v.discriminator | some v in violations}) == 2
}
