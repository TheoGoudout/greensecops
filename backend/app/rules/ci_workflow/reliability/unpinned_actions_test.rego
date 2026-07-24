package greensecops.ci_workflow.reliability.unpinned_actions_test

import data.greensecops.ci_workflow.reliability.unpinned_actions
import rego.v1

test_violation_action_at_main if {
	violations := unpinned_actions.violations with input as {"jobs": {"build": {"steps": [{"uses": "actions/checkout@main"}]}}}
	count(violations) == 1
	some v in violations
	v.rule == "unpinned_actions"
}

test_violation_action_at_bare_version if {
	violations := unpinned_actions.violations with input as {"jobs": {"build": {"steps": [{"uses": "actions/setup-node@v3"}]}}}
	count(violations) == 1
}

test_no_violation_sha_pinned if {
	violations := unpinned_actions.violations with input as {"jobs": {"build": {"steps": [{"uses": "actions/checkout@a81bbbf8298c0fa03ea29cdc473d45769f953675"}]}}}
	count(violations) == 0
}

test_no_violation_semver_tag if {
	violations := unpinned_actions.violations with input as {"jobs": {"build": {"steps": [{"uses": "actions/setup-python@v5.1.0"}]}}}
	count(violations) == 0
}

test_violation_action_at_latest if {
	violations := unpinned_actions.violations with input as {"jobs": {"ci": {"steps": [{"uses": "some-org/some-action@latest"}]}}}
	count(violations) == 1
}

test_violation_emits_step_index if {
	violations := unpinned_actions.violations with input as {
		"jobs": {
			"build": {
				"steps": [
					{"uses": "actions/checkout@a81bbbf8298c0fa03ea29cdc473d45769f953675"},
					{"uses": "actions/setup-node@v3"},
				],
			},
		},
	}
	count(violations) == 1
	some v in violations
	v.step_index == 1
}

test_same_action_twice_yields_two_violations if {
	violations := unpinned_actions.violations with input as {
		"jobs": {
			"build": {
				"steps": [
					{"uses": "actions/checkout@main"},
					{"run": "make build"},
					{"uses": "actions/checkout@main"},
				],
			},
		},
	}
	count(violations) == 2
	{v.step_index | some v in violations} == {0, 2}
}
