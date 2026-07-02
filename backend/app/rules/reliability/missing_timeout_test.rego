package greensecops.reliability.missing_timeout_test

import data.greensecops.reliability.missing_timeout
import rego.v1

test_violation_when_no_timeout if {
	violations := missing_timeout.violations with input as {
		"jobs": {
			"build": {
				"runs-on": "ubuntu-latest",
				"steps": [{"uses": "actions/checkout@v4"}],
			},
		},
	}
	count(violations) == 1
}

test_no_violation_when_timeout_set if {
	violations := missing_timeout.violations with input as {
		"jobs": {
			"build": {
				"runs-on": "ubuntu-latest",
				"timeout-minutes": 30,
				"steps": [{"uses": "actions/checkout@v4"}],
			},
		},
	}
	count(violations) == 0
}

test_violation_only_for_jobs_without_timeout if {
	violations := missing_timeout.violations with input as {
		"jobs": {
			"build": {
				"runs-on": "ubuntu-latest",
				"timeout-minutes": 30,
				"steps": [],
			},
			"deploy": {
				"runs-on": "ubuntu-latest",
				"steps": [],
			},
		},
	}
	count(violations) == 1
	some v in violations
	v.job == "deploy"
}
