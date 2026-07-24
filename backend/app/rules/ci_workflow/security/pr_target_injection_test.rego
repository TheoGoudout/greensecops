package greensecops.ci_workflow.security.pr_target_injection_test

import data.greensecops.ci_workflow.security.pr_target_injection
import rego.v1

test_violation_pr_target_with_head_checkout if {
	violations := pr_target_injection.violations with input as {
		"on": {"pull_request_target": {}},
		"jobs": {
			"build": {
				"steps": [
					{
						"uses": "actions/checkout@v4",
						"with": {"ref": "${{ github.event.pull_request.head.sha }}"},
					},
				],
			},
		},
	}
	count(violations) == 1
	some v in violations
	v.rule == "pr_target_injection"
	v.severity == "critical"
}

test_no_violation_pr_target_safe_checkout if {
	violations := pr_target_injection.violations with input as {
		"on": {"pull_request_target": {}},
		"jobs": {"build": {"steps": [{"uses": "actions/checkout@v4"}]}},
	}
	count(violations) == 0
}

test_no_violation_pull_request_with_head_checkout if {
	violations := pr_target_injection.violations with input as {
		"on": {"pull_request": {}},
		"jobs": {
			"build": {
				"steps": [
					{
						"uses": "actions/checkout@v4",
						"with": {"ref": "${{ github.event.pull_request.head.sha }}"},
					},
				],
			},
		},
	}
	count(violations) == 0
}
