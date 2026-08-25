package greensecops.ci_workflow.reliability.unsound_contains_test

import data.greensecops.ci_workflow.reliability.unsound_contains as rule
import rego.v1

test_violation_space_joined_haystack_job_if if {
	violations := rule.violations with input as {"jobs": {"deploy": {
		"if": "contains('refs/heads/main refs/heads/release', github.ref)",
		"steps": [{"run": "./deploy.sh"}],
	}}}
	count(violations) == 1
	some v in violations
	v.rule == "unsound_contains"
	v.job == "deploy"
}

test_violation_comma_joined_haystack if {
	violations := rule.violations with input as {"jobs": {"deploy": {
		"if": "contains('main,release', github.ref_name)",
		"steps": [],
	}}}
	count(violations) == 1
}

test_violation_step_if if {
	violations := rule.violations with input as {"jobs": {"deploy": {"steps": [
		{"name": "Ship", "if": "${{ contains('alpha beta', matrix.env) }}", "run": "./ship.sh"},
	]}}}
	count(violations) == 1
	some v in violations
	v.step_index == 0
}

# ─── Does not fire ───────────────────────────────────────────────────────────

# The list form is the fix.
test_no_violation_fromjson_list if {
	violations := rule.violations with input as {"jobs": {"deploy": {
		"if": "contains(fromJSON('[\"refs/heads/main\", \"refs/heads/release\"]'), github.ref)",
		"steps": [],
	}}}
	count(violations) == 0
}

# The legitimate substring use: the haystack is a context value, not a literal.
test_no_violation_substring_of_commit_message if {
	violations := rule.violations with input as {"jobs": {"build": {
		"if": "!contains(github.event.head_commit.message, 'skip ci')",
		"steps": [],
	}}}
	count(violations) == 0
}

# A single-value literal carries no separator, so it was never meant as a list.
test_no_violation_single_value_literal if {
	violations := rule.violations with input as {"jobs": {"deploy": {
		"if": "contains('refs/heads/main', github.ref)",
		"steps": [],
	}}}
	count(violations) == 0
}

test_no_violation_no_contains_at_all if {
	violations := rule.violations with input as {"jobs": {"deploy": {
		"if": "github.ref == 'refs/heads/main'",
		"steps": [{"run": "./deploy.sh"}],
	}}}
	count(violations) == 0
}
