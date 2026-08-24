package greensecops.ci_workflow.reliability.unsound_condition_test

import data.greensecops.ci_workflow.reliability.unsound_condition
import rego.v1

test_violation_two_expression_groups_in_a_step if {
	violations := unsound_condition.violations with input as {"jobs": {"deploy": {"steps": [{
		"if": "${{ github.event_name == 'push' }} && ${{ github.ref == 'refs/heads/main' }}",
		"run": "./deploy.sh",
	}]}}}
	count(violations) == 1
	some v in violations
	v.rule == "unsound_condition"
	v.step_index == 0
}

test_violation_two_expression_groups_in_a_job if {
	violations := unsound_condition.violations with input as {"jobs": {"deploy": {
		"if": "${{ success() }} || ${{ failure() }}",
		"steps": [],
	}}}
	count(violations) == 1
	some v in violations
	v.job == "deploy"
}

# A single wrapper with text hanging off the end fails the same way: the result
# is a string, and a non-empty string is true.
test_violation_expression_with_trailing_text if {
	violations := unsound_condition.violations with input as {"jobs": {"j": {"steps": [
		{"if": "${{ github.event_name == 'push' }} && github.ref == 'refs/heads/main'", "run": "x"},
	]}}}
	count(violations) == 1
}

# ─── Does not fire ───────────────────────────────────────────────────────────

test_no_violation_bare_expression if {
	violations := unsound_condition.violations with input as {"jobs": {"deploy": {"steps": [
		{"if": "github.event_name == 'push' && github.ref == 'refs/heads/main'", "run": "./deploy.sh"},
	]}}}
	count(violations) == 0
}

# One wrapper around the whole condition is the correct form.
test_no_violation_single_wrapper_enclosing_everything if {
	violations := unsound_condition.violations with input as {"jobs": {"deploy": {"steps": [
		{"if": "${{ github.event_name == 'push' && github.ref == 'refs/heads/main' }}", "run": "./deploy.sh"},
	]}}}
	count(violations) == 0
}

test_no_violation_without_a_condition if {
	violations := unsound_condition.violations with input as {"jobs": {"j": {"steps": [{"run": "make"}]}}}
	count(violations) == 0
}

test_no_violation_on_a_non_workflow_document if {
	violations := unsound_condition.violations with input as {"resource": [{"aws_s3_bucket": {"b": {}}}]}
	count(violations) == 0
}
