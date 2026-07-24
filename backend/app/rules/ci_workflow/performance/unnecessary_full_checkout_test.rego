package greensecops.ci_workflow.performance.unnecessary_full_checkout_test

import data.greensecops.ci_workflow.performance.unnecessary_full_checkout
import rego.v1

test_violation_fetch_depth_zero_no_git_commands if {
	violations := unnecessary_full_checkout.violations with input as {
		"jobs": {
			"build": {
				"steps": [
					{
						"uses": "actions/checkout@v4",
						"with": {"fetch-depth": 0},
					},
					{"run": "npm ci && npm test"},
				],
			},
		},
	}
	count(violations) == 1
	some v in violations
	v.rule == "unnecessary_full_checkout"
	v.job == "build"
}

test_no_violation_fetch_depth_zero_with_git_log if {
	violations := unnecessary_full_checkout.violations with input as {
		"jobs": {
			"release": {
				"steps": [
					{
						"uses": "actions/checkout@v4",
						"with": {"fetch-depth": 0},
					},
					{"run": "git log --oneline -10"},
				],
			},
		},
	}
	count(violations) == 0
}

test_no_violation_fetch_depth_zero_with_semantic_release if {
	violations := unnecessary_full_checkout.violations with input as {
		"jobs": {
			"release": {
				"steps": [
					{
						"uses": "actions/checkout@v4",
						"with": {"fetch-depth": 0},
					},
					{"run": "npx semantic-release"},
				],
			},
		},
	}
	count(violations) == 0
}

test_no_violation_default_fetch_depth if {
	violations := unnecessary_full_checkout.violations with input as {
		"jobs": {
			"build": {
				"steps": [
					{
						"uses": "actions/checkout@v4",
						"with": {"fetch-depth": 1},
					},
					{"run": "npm test"},
				],
			},
		},
	}
	count(violations) == 0
}

test_no_violation_no_checkout_step if {
	violations := unnecessary_full_checkout.violations with input as {"jobs": {"build": {"steps": [{"run": "echo hello"}]}}}
	count(violations) == 0
}

test_no_violation_fetch_depth_zero_with_prek_from_ref if {
	violations := unnecessary_full_checkout.violations with input as {
		"jobs": {
			"pre-commit": {
				"steps": [
					{
						"uses": "actions/checkout@v4",
						"with": {"fetch-depth": 0},
					},
					{"run": "uvx prek run --from-ref origin/main --to-ref HEAD"},
				],
			},
		},
	}
	count(violations) == 0
}

test_no_violation_fetch_depth_zero_with_precommit_from_ref if {
	violations := unnecessary_full_checkout.violations with input as {
		"jobs": {
			"lint": {
				"steps": [
					{
						"uses": "actions/checkout@v4",
						"with": {"fetch-depth": 0},
					},
					{"run": "pre-commit run --from-ref origin/main --to-ref HEAD"},
				],
			},
		},
	}
	count(violations) == 0
}
