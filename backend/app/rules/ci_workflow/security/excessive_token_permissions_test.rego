package greensecops.ci_workflow.security.excessive_token_permissions_test

import data.greensecops.ci_workflow.security.excessive_token_permissions as excessive_permissions
import rego.v1

# Three independent clauses at three severities. That is why this rule's
# annotation block declares the worst case rather than matching the body
# exactly — it is the one entry in the allow-list in
# tests/core/test_rule_registry.py. Each clause is pinned separately here,
# including the fact that they do not collapse into one.

_checkout_job := {"runs-on": "ubuntu-latest", "steps": [{"uses": "actions/checkout@v5"}]}

test_critical_violation_for_write_all if {
	violations := excessive_permissions.violations with input as {
		"permissions": "write-all",
		"jobs": {"build": _checkout_job},
	}
	count(violations) == 1
	some v in violations
	v.severity == "critical"
	v.job == null
}

test_high_violation_for_more_than_three_write_scopes if {
	violations := excessive_permissions.violations with input as {
		"permissions": {
			"contents": "write",
			"packages": "write",
			"issues": "write",
			"pull-requests": "write",
		},
		"jobs": {"build": _checkout_job},
	}
	count(violations) == 1
	some v in violations
	v.severity == "high"
}

test_no_violation_at_exactly_three_write_scopes if {
	violations := excessive_permissions.violations with input as {
		"permissions": {"contents": "write", "packages": "write", "issues": "write"},
		"jobs": {"build": _checkout_job},
	}
	count(violations) == 0
}

test_medium_violation_when_nothing_declares_permissions if {
	violations := excessive_permissions.violations with input as {"jobs": {"build": _checkout_job}}
	count(violations) == 1
	some v in violations
	v.severity == "medium"
	v.job == "build"
}

# A job-level block satisfies the third clause on its own.
test_no_violation_when_the_job_declares_its_own_permissions if {
	violations := excessive_permissions.violations with input as {"jobs": {"build": {
		"permissions": {"contents": "read"},
		"steps": [{"uses": "actions/checkout@v5"}],
	}}}
	count(violations) == 0
}

# The third clause is scoped to jobs that actually use a first-party action,
# since that is what consumes the token.
test_no_violation_for_a_job_with_no_actions_steps if {
	violations := excessive_permissions.violations with input as {"jobs": {"build": {
		"runs-on": "ubuntu-latest",
		"steps": [{"run": "make build"}],
	}}}
	count(violations) == 0
}

test_no_violation_for_a_least_privilege_workflow if {
	violations := excessive_permissions.violations with input as {
		"permissions": {"contents": "read"},
		"jobs": {"build": _checkout_job},
	}
	count(violations) == 0
}

# read-all is over-broad but grants no writes, so it is not this finding.
test_no_violation_for_read_all if {
	violations := excessive_permissions.violations with input as {
		"permissions": "read-all",
		"jobs": {"build": _checkout_job},
	}
	count(violations) == 0
}

test_each_undeclared_job_is_its_own_finding if {
	violations := excessive_permissions.violations with input as {"jobs": {
		"build": _checkout_job,
		"test": _checkout_job,
	}}
	count(violations) == 2
	{v.job | some v in violations} == {"build", "test"}
}
