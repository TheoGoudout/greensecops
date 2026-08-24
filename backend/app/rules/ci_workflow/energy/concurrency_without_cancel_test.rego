package greensecops.ci_workflow.energy.concurrency_without_cancel_test

import data.greensecops.ci_workflow.energy.concurrency_without_cancel as without_cancel
import rego.v1

test_violation_when_cancel_is_absent if {
	violations := without_cancel.violations with input as {"concurrency": {"group": "ci-${{ github.ref }}"}}
	count(violations) == 1
	some v in violations
	v.discriminator == "workflow"
}

test_violation_for_the_bare_string_shorthand if {
	violations := without_cancel.violations with input as {"concurrency": "ci-${{ github.ref }}"}
	count(violations) == 1
}

# An explicit `false` is a deliberate choice — the right one on a deploy group.
test_no_violation_when_cancel_is_explicitly_false if {
	violations := without_cancel.violations with input as {"concurrency": {
		"group": "deploy-production",
		"cancel-in-progress": false,
	}}
	count(violations) == 0
}

test_no_violation_when_cancel_is_true if {
	violations := without_cancel.violations with input as {"concurrency": {
		"group": "ci-${{ github.ref }}",
		"cancel-in-progress": true,
	}}
	count(violations) == 0
}

# An expression is a deliberate decision the rule should not second-guess —
# it commonly reads `${{ github.ref != 'refs/heads/main' }}`.
test_no_violation_when_cancel_is_an_expression if {
	violations := without_cancel.violations with input as {"concurrency": {
		"group": "ci-${{ github.ref }}",
		"cancel-in-progress": "${{ github.ref != 'refs/heads/main' }}",
	}}
	count(violations) == 0
}

# This rule is about a group that exists; missing_concurrency covers absence.
test_no_violation_when_no_concurrency_is_declared if {
	violations := without_cancel.violations with input as {"jobs": {"build": {"steps": []}}}
	count(violations) == 0
}

test_violation_for_a_job_level_group if {
	violations := without_cancel.violations with input as {"jobs": {"deploy": {
		"concurrency": {"group": "deploy-${{ github.ref }}"},
		"steps": [],
	}}}
	count(violations) == 1
	some v in violations
	v.job == "deploy"
}

test_no_violation_for_a_job_level_group_that_cancels if {
	violations := without_cancel.violations with input as {"jobs": {"deploy": {
		"concurrency": {"group": "deploy-${{ github.ref }}", "cancel-in-progress": true},
		"steps": [],
	}}}
	count(violations) == 0
}

test_workflow_and_job_level_are_separate_findings if {
	violations := without_cancel.violations with input as {
		"concurrency": {"group": "ci-${{ github.ref }}"},
		"jobs": {"deploy": {"concurrency": {"group": "deploy"}, "steps": []}},
	}
	count(violations) == 2
	count({v.discriminator | some v in violations}) == 2
}
