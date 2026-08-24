package greensecops.ci_workflow.security.excessive_token_permissions_test

import data.greensecops.ci_workflow.security.excessive_token_permissions as write_all
import rego.v1

test_violation_for_workflow_write_all if {
	violations := write_all.violations with input as {"permissions": "write-all"}
	count(violations) == 1
	some v in violations
	v.severity == "critical"
	v.discriminator == "workflow"
}

test_violation_for_job_write_all if {
	violations := write_all.violations with input as {"jobs": {"build": {"permissions": "write-all"}}}
	count(violations) == 1
	some v in violations
	v.job == "build"
}

test_both_are_reported_separately if {
	violations := write_all.violations with input as {
		"permissions": "write-all",
		"jobs": {"build": {"permissions": "write-all"}},
	}
	count(violations) == 2
	count({v.discriminator | some v in violations}) == 2
}

test_no_violation_for_the_deny_all_baseline if {
	count(write_all.violations) == 0 with input as {"permissions": {}}
}

test_no_violation_for_an_explicit_scope_list if {
	count(write_all.violations) == 0 with input as {"permissions": {"contents": "read"}}
}

# The clause that reported a job with no permissions block moved out entirely:
# `missing_top_level_permissions` already reports that workflow.
test_no_violation_for_a_job_without_permissions if {
	count(write_all.violations) == 0 with input as {"jobs": {"build": {"steps": [{"uses": "actions/checkout@v4"}]}}}
}
