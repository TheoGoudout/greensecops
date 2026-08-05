package greensecops.ci_workflow.security.job_permissions_wider_than_workflow_test

import data.greensecops.ci_workflow.security.job_permissions_wider_than_workflow as wider_perms
import rego.v1

_workflow(workflow_perms, job_perms) := {
	"permissions": workflow_perms,
	"jobs": {"build": {
		"runs-on": "ubuntu-latest",
		"permissions": job_perms,
		"steps": [],
		"__start_line__": 5,
		"__end_line__": 12,
	}},
}

test_violation_when_a_job_adds_a_write_scope if {
	violations := wider_perms.violations with input as _workflow(
		{"contents": "read"},
		{"contents": "write"},
	)
	count(violations) == 1
	some v in violations
	v.job == "build"
	v.severity == "medium"
}

test_no_violation_when_the_job_matches_the_default if {
	violations := wider_perms.violations with input as _workflow(
		{"contents": "write"},
		{"contents": "write"},
	)
	count(violations) == 0
}

test_no_violation_when_the_job_narrows_the_default if {
	violations := wider_perms.violations with input as _workflow(
		{"contents": "write"},
		{"contents": "read"},
	)
	count(violations) == 0
}

# write-all already grants everything, so no job block can widen it —
# excessive_token_permissions reports that far larger problem.
test_no_violation_when_the_workflow_default_is_write_all if {
	violations := wider_perms.violations with input as _workflow(
		"write-all",
		{"contents": "write", "packages": "write"},
	)
	count(violations) == 0
}

test_no_violation_for_a_job_with_no_permissions_block if {
	violations := wider_perms.violations with input as {
		"permissions": {"contents": "read"},
		"jobs": {"build": {"runs-on": "ubuntu-latest", "steps": []}},
	}
	count(violations) == 0
}

# A workflow with no default inherits the repository setting, which this rule
# cannot see — so a job block is not evidence of widening.
test_violation_when_the_workflow_declares_no_default if {
	violations := wider_perms.violations with input as {
		"jobs": {"build": {
			"runs-on": "ubuntu-latest",
			"permissions": {"contents": "write"},
			"steps": [],
		}},
	}
	count(violations) == 1
}

test_the_finding_carries_the_job_line_span if {
	violations := wider_perms.violations with input as _workflow(
		{"contents": "read"},
		{"contents": "write"},
	)
	some v in violations
	v.line_start == 5
	v.line_end == 12
}

test_each_widened_scope_is_its_own_finding if {
	violations := wider_perms.violations with input as _workflow(
		{"contents": "read"},
		{"contents": "write", "packages": "write", "issues": "read"},
	)
	count(violations) == 2
	count({v.discriminator | some v in violations}) == 2
}
