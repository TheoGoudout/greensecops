package greensecops.energy.runner_sizing_test

import data.greensecops.energy.runner_sizing
import rego.v1

test_violation_large_runner_few_steps if {
	violations := runner_sizing.violations with input as {
		"jobs": {
			"build": {
				"runs-on": "ubuntu-latest-large",
				"steps": [
					{"uses": "actions/checkout@v4"},
					{"run": "echo hello"},
				],
			},
		},
	}
	count(violations) == 1
	some v in violations
	v.rule == "runner_sizing"
}

test_no_violation_large_runner_many_steps if {
	violations := runner_sizing.violations with input as {
		"jobs": {
			"build": {
				"runs-on": "ubuntu-latest-large",
				"steps": [
					{"uses": "actions/checkout@v4"},
					{"run": "step2"},
					{"run": "step3"},
					{"run": "step4"},
				],
			},
		},
	}
	count(violations) == 0
}

test_no_violation_standard_runner_few_steps if {
	violations := runner_sizing.violations with input as {
		"jobs": {
			"build": {
				"runs-on": "ubuntu-latest",
				"steps": [{"uses": "actions/checkout@v4"}],
			},
		},
	}
	count(violations) == 0
}

test_violation_xlarge_runner if {
	violations := runner_sizing.violations with input as {
		"jobs": {
			"ci": {
				"runs-on": "ubuntu-xlarge",
				"steps": [{"run": "echo hi"}],
			},
		},
	}
	count(violations) == 1
}
