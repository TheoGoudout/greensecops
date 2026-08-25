package greensecops.ci_workflow.security.token_permissions_too_broad_test

import data.greensecops.ci_workflow.security.token_permissions_too_broad as too_broad
import rego.v1

test_violation_for_four_write_scopes if {
	violations := too_broad.violations with input as {"permissions": {
		"contents": "write",
		"packages": "write",
		"deployments": "write",
		"issues": "write",
	}}
	count(violations) == 1
	some v in violations
	v.severity == "high"
}

test_no_violation_for_three_write_scopes if {
	violations := too_broad.violations with input as {"permissions": {
		"contents": "write",
		"packages": "write",
		"deployments": "write",
	}}
	count(violations) == 0
}

test_no_violation_when_the_extra_scopes_are_read if {
	violations := too_broad.violations with input as {"permissions": {
		"contents": "write",
		"packages": "read",
		"deployments": "read",
		"issues": "read",
		"actions": "read",
	}}
	count(violations) == 0
}

test_no_violation_for_the_deny_all_baseline if {
	count(too_broad.violations) == 0 with input as {"permissions": {}}
}

# `write-all` is a string, not a mapping — `excessive_token_permissions` owns it.
test_no_violation_for_write_all if {
	count(too_broad.violations) == 0 with input as {"permissions": "write-all"}
}

test_message_lists_the_scopes if {
	violations := too_broad.violations with input as {"permissions": {
		"contents": "write",
		"packages": "write",
		"deployments": "write",
		"issues": "write",
	}}
	some v in violations
	v.context == "contents, deployments, issues, packages"
}
