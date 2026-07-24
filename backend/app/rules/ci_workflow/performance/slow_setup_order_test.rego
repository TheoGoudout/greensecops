package greensecops.ci_workflow.performance.slow_setup_order_test

import data.greensecops.ci_workflow.performance.slow_setup_order
import rego.v1

test_violation_install_before_lint if {
	violations := slow_setup_order.violations with input as {
		"jobs": {
			"ci": {
				"steps": [
					{"uses": "actions/setup-node@v4"},
					{"run": "npm install"},
					{"run": "npm run lint"},
				],
			},
		},
	}
	count(violations) == 1
	some v in violations
	v.rule == "slow_setup_order"
}

test_no_violation_lint_before_install if {
	violations := slow_setup_order.violations with input as {
		"jobs": {
			"ci": {
				"steps": [
					{"uses": "actions/setup-node@v4"},
					{"run": "npm run lint"},
					{"run": "npm install"},
					{"run": "npm test"},
				],
			},
		},
	}
	count(violations) == 0
}

test_no_violation_no_lint_step if {
	violations := slow_setup_order.violations with input as {
		"jobs": {
			"build": {
				"steps": [
					{"uses": "actions/setup-node@v4"},
					{"run": "npm install"},
					{"run": "npm test"},
				],
			},
		},
	}
	count(violations) == 0
}
