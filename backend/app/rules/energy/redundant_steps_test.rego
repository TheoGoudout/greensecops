package greensecops.energy.redundant_steps_test

import data.greensecops.energy.redundant_steps
import rego.v1

test_violation_action_in_more_than_two_jobs if {
	violations := redundant_steps.violations with input as {
		"jobs": {
			"job1": {"steps": [{"uses": "actions/checkout@v4"}]},
			"job2": {"steps": [{"uses": "actions/checkout@v4"}]},
			"job3": {"steps": [{"uses": "actions/checkout@v4"}]},
		},
	}
	count(violations) > 0
	some v in violations
	v.rule == "redundant_steps"
}

test_no_violation_action_in_two_jobs if {
	violations := redundant_steps.violations with input as {
		"jobs": {
			"job1": {"steps": [{"uses": "actions/checkout@v4"}]},
			"job2": {"steps": [{"uses": "actions/checkout@v4"}]},
		},
	}
	count(violations) == 0
}

test_no_violation_different_actions if {
	violations := redundant_steps.violations with input as {
		"jobs": {
			"job1": {"steps": [{"uses": "actions/checkout@v4"}]},
			"job2": {"steps": [{"uses": "actions/setup-node@v4"}]},
			"job3": {"steps": [{"uses": "actions/setup-python@v5"}]},
		},
	}
	count(violations) == 0
}
